"""
Парсер объявлений сайта realty.yandex.ru.

Используется для автозаполнения карточки объекта недвижимости после
выбора адреса в подсказках DaData. Идея: сотрудник выбирает адрес в
DaData -> мы конструируем поисковый запрос на realty.yandex.ru ->
получаем список похожих объявлений -> сотрудник выбирает подходящее ->
поля карточки (цена, площадь, описание, фото и т.д.) подставляются
автоматически.

Модуль НИКОГДА не сохраняет ничего в БД самостоятельно — он отдаёт
структуры данных, которые потом передаются на фронтенд и
докручиваются сотрудником вручную перед сохранением.

Архитектурные принципы:
    * Чёрный список не нарушаем — используем разумные таймауты
      (``YANDEX_REALTY_MIN_DELAY`` / ``YANDEX_REALTY_MAX_DELAY``),
      ротацию User-Agent, single-session с keep-alive.
    * Парсим то, что отдаётся в HTML: основная цель — JSON-блок
      ``<script id="__NEXT_DATA__">``, fallback — JSON-LD,
      OG-meta-теги, регулярки.
    * Если Яндекс показал капчу или 4xx/5xx — выбрасываем
      :class:`YandexRealtyBlocked` / :class:`YandexRealtyError`.
      Эти исключения превращаются в HTTP 503 на уровне view.
    * НИЧЕГО про DaData не знаем напрямую — работаем со словарём
      адреса в формате :func:`key.dadata.DadataClient._normalize`.

Ключ к Яндексу/прокси не нужен: парсер обращается к публичным
страницам. На случай блокировок предусмотрен опциональный HTTP-прокси
через настройку ``YANDEX_REALTY_PROXY_URL``.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Optional
from urllib.parse import quote, urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Константы парсера
# --------------------------------------------------------------------------

BASE_URL = 'https://realty.yandex.ru'

# Список реалистичных User-Agent. Ротируем между запросами, чтобы не
# выглядеть как один и тот же бот. Подобраны из реальных Chrome/Firefox
# на Windows/Mac — самые «обычные» комбинации.
USER_AGENTS = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
    '(KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) '
    'Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
)

# Преобразование «человеческих» русских названий городов в slug, который
# использует realty.yandex.ru в URL. Это закрывает 95% реальных кейсов
# для дипломного демо. Если города в карте нет — fallback в общий
# поиск через ?text=...
CITY_SLUGS: dict[str, str] = {
    'москва': 'moskva',
    'санкт-петербург': 'sankt-peterburg',
    'спб': 'sankt-peterburg',
    'питер': 'sankt-peterburg',
    'новосибирск': 'novosibirsk',
    'екатеринбург': 'ekaterinburg',
    'нижний новгород': 'nizhniy-novgorod',
    'казань': 'kazan',
    'челябинск': 'chelyabinsk',
    'омск': 'omsk',
    'самара': 'samara',
    'ростов-на-дону': 'rostov-na-donu',
    'уфа': 'ufa',
    'красноярск': 'krasnoyarsk',
    'пермь': 'perm',
    'воронеж': 'voronezh',
    'волгоград': 'volgograd',
    'краснодар': 'krasnodar',
    'саратов': 'saratov',
    'тюмень': 'tyumen',
    'тольятти': 'tolyatti',
    'ижевск': 'izhevsk',
    'барнаул': 'barnaul',
    'ульяновск': 'ulyanovsk',
    'иркутск': 'irkutsk',
    'хабаровск': 'habarovsk',
    'ярославль': 'yaroslavl',
    'владивосток': 'vladivostok',
    'махачкала': 'mahachkala',
    'томск': 'tomsk',
    'оренбург': 'orenburg',
    'кемерово': 'kemerovo',
    'новокузнецк': 'novokuznetsk',
    'рязань': 'ryazan',
    'астрахань': 'astrahan',
    'набережные челны': 'naberezhnye-chelny',
    'пенза': 'penza',
    'липецк': 'lipeck',
    'киров': 'kirov',
    'тула': 'tula',
    'чебоксары': 'cheboksary',
    'калининград': 'kaliningrad',
    'брянск': 'bryansk',
    'курск': 'kursk',
    'иваново': 'ivanovo',
    'магнитогорск': 'magnitogorsk',
    'тверь': 'tver',
    'ставрополь': 'stavropol',
    'нижний тагил': 'nizhniy-tagil',
    'белгород': 'belgorod',
    'архангельск': 'arhangelsk',
    'владимир': 'vladimir',
    'сочи': 'sochi',
    'курган': 'kurgan',
    'смоленск': 'smolensk',
    'калуга': 'kaluga',
    'чита': 'chita',
    'орёл': 'orel',
    'орел': 'orel',
    'волжский': 'volzhskiy',
    'череповец': 'cherepovec',
    'владикавказ': 'vladikavkaz',
    'мурманск': 'murmansk',
    'сургут': 'surgut',
    'вологда': 'vologda',
    'тамбов': 'tambov',
    'стерлитамак': 'sterlitamak',
    'грозный': 'groznyy',
    'якутск': 'yakutsk',
    'кострома': 'kostroma',
    'комсомольск-на-амуре': 'komsomolsk-na-amure',
    'петрозаводск': 'petrozavodsk',
    'таганрог': 'taganrog',
    'нижневартовск': 'nizhnevartovsk',
    'йошкар-ола': 'yoshkar-ola',
    'братск': 'bratsk',
    'новороссийск': 'novorossiysk',
    'дзержинск': 'dzerzhinsk',
    'шахты': 'shahty',
    'нальчик': 'nalchik',
    'орск': 'orsk',
    'сыктывкар': 'syktyvkar',
    'нижнекамск': 'nizhnekamsk',
    'ангарск': 'angarsk',
    'старый оскол': 'staryy-oskol',
    'великий новгород': 'velikiy-novgorod',
    'благовещенск': 'blagoveshchensk',
    'химки': 'himki',
    'псков': 'pskov',
    'бийск': 'biysk',
    'прокопьевск': 'prokopevsk',
    'энгельс': 'engels',
    'рыбинск': 'rybinsk',
    'балашиха': 'balashiha',
    'северодвинск': 'severodvinsk',
    'армавир': 'armavir',
    'подольск': 'podolsk',
    'королёв': 'korolev',
    'королев': 'korolev',
    'южно-сахалинск': 'yuzhno-sahalinsk',
    'петропавловск-камчатский': 'petropavlovsk-kamchatskiy',
    'сызрань': 'syzran',
    'норильск': 'norilsk',
    'златоуст': 'zlatoust',
    'каменск-уральский': 'kamensk-uralskiy',
    'мытищи': 'mytishchi',
    'люберцы': 'lyubercy',
    'волгодонск': 'volgodonsk',
    'абакан': 'abakan',
    'новочеркасск': 'novocherkassk',
}


# --------------------------------------------------------------------------
# Исключения и DTO
# --------------------------------------------------------------------------

class YandexRealtyError(Exception):
    """Базовая ошибка парсера realty.yandex.ru."""


class YandexRealtyBlocked(YandexRealtyError):
    """Запрос заблокирован (CAPTCHA / 429 / 403)."""


class YandexRealtyDisabled(YandexRealtyError):
    """Парсер отключён настройкой ``YANDEX_REALTY_ENABLED=False``."""


@dataclass
class YandexOffer:
    """
    Нормализованное представление одного объявления с realty.yandex.ru.

    Структура полей подобрана так, чтобы покрывать поля модели
    :class:`key.models.Property` и :class:`key.models.PropertyPhoto`:
    то есть фронт, получив этот объект, может сразу заполнить форму
    создания/редактирования объекта.
    """
    source: str = 'yandex_realty'
    url: str = ''
    title: str = ''
    description: str = ''
    price: Optional[float] = None
    price_per_sqm: Optional[float] = None
    currency: str = 'RUB'
    rooms_count: Optional[int] = None
    floor_number: Optional[int] = None
    total_floors: Optional[int] = None
    area_total: Optional[float] = None
    area_living: Optional[float] = None
    area_kitchen: Optional[float] = None
    address: str = ''
    geo_lat: Optional[float] = None
    geo_lon: Optional[float] = None
    photos: list[str] = field(default_factory=list)
    deal_type: Optional[str] = None  # 'sell' | 'rent'
    property_type: Optional[str] = None  # 'kvartira' | 'komnata' | ...
    raw_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Сам парсер
# --------------------------------------------------------------------------

class YandexRealtyParser:
    """
    Тонкая обёртка над requests + BeautifulSoup для realty.yandex.ru.

    Использование::

        parser = YandexRealtyParser()
        offers = parser.search_by_address(dadata_address_dict, limit=10)
        # ... сотрудник выбирает оффер ...
        offer = parser.parse_offer(offers[0]['url'])
    """

    def __init__(
        self,
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        timeout: Optional[float] = None,
        retries: int = 2,
        proxy_url: Optional[str] = None,
    ):
        # Параметры читаем из настроек, а не хардкодим — чтобы
        # дипломный стенд можно было тонко настроить под медленный
        # канал/частые блокировки без правки кода.
        self.min_delay = float(
            min_delay if min_delay is not None
            else getattr(settings, 'YANDEX_REALTY_MIN_DELAY', 2.0)
        )
        self.max_delay = float(
            max_delay if max_delay is not None
            else getattr(settings, 'YANDEX_REALTY_MAX_DELAY', 5.0)
        )
        if self.max_delay < self.min_delay:
            self.max_delay = self.min_delay
        self.timeout = float(
            timeout if timeout is not None
            else getattr(settings, 'YANDEX_REALTY_TIMEOUT', 20.0)
        )
        self.retries = max(1, int(retries))
        proxy = proxy_url or getattr(settings, 'YANDEX_REALTY_PROXY_URL', '') or ''
        self._proxies = {'http': proxy, 'https': proxy} if proxy else None

        self.session = requests.Session()
        # Базовые куки, которые Яндекс сам выставит при первом GET.
        # Прогреваем сессию через обращение к корню сайта — это
        # уменьшает шанс капчи на самом первом «холодном» запросе.
        self._warmed_up = False
        self._last_request_at = 0.0

    # ------------------------------------------------------------------
    # Защита от банов
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """Гарантирует паузу min_delay..max_delay между запросами."""
        elapsed = time.monotonic() - self._last_request_at
        wait = random.uniform(self.min_delay, self.max_delay)
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last_request_at = time.monotonic()

    def _headers(self, referer: Optional[str] = None) -> dict[str, str]:
        ua = random.choice(USER_AGENTS)
        headers = {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;'
                      'q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin' if referer else 'none',
            'Sec-Fetch-User': '?1',
        }
        if referer:
            headers['Referer'] = referer
        return headers

    def _warm_up(self) -> None:
        if self._warmed_up:
            return
        try:
            self._http_get(BASE_URL + '/', referer=None, _is_warmup=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug('Не удалось прогреть сессию Яндекса: %s', exc)
        finally:
            self._warmed_up = True

    def _http_get(
        self,
        url: str,
        params: Optional[dict] = None,
        referer: Optional[str] = None,
        _is_warmup: bool = False,
    ) -> requests.Response:
        """Низкоуровневый GET с тротлингом, ретраями и детекцией капчи."""
        self._throttle()
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=self._headers(referer=referer),
                    timeout=self.timeout,
                    proxies=self._proxies,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning(
                    'Yandex.Realty сетевая ошибка (попытка %s/%s) %s: %s',
                    attempt, self.retries, url, exc,
                )
                # Перед повтором ждём чуть дольше, чтобы не долбить.
                time.sleep(self.min_delay * attempt)
                continue

            # Капча: Яндекс редиректит на showcaptcha или вшивает
            # строку CAPTCHA в первые килобайты HTML.
            final_url = response.url or ''
            if 'showcaptcha' in final_url or '/checkcaptcha' in final_url:
                raise YandexRealtyBlocked(
                    'Яндекс показал капчу. Увеличьте таймауты или используйте прокси.'
                )

            if response.status_code in (403, 429):
                # Не повторяем агрессивно — это явный сигнал бана.
                raise YandexRealtyBlocked(
                    f'Yandex.Realty вернул HTTP {response.status_code}. '
                    f'Возможно, IP временно заблокирован.'
                )

            if 500 <= response.status_code < 600:
                last_exc = YandexRealtyError(
                    f'Yandex.Realty HTTP {response.status_code}'
                )
                logger.warning(
                    'Yandex.Realty %s (попытка %s/%s) %s',
                    response.status_code, attempt, self.retries, url,
                )
                time.sleep(self.min_delay * attempt)
                continue

            if response.status_code >= 400:
                raise YandexRealtyError(
                    f'Yandex.Realty HTTP {response.status_code} на {url}'
                )

            # Текстовая капча в теле ответа (резервная проверка).
            if not _is_warmup:
                head = response.text[:8000].lower()
                if 'showcaptcha' in head or 'are you a robot' in head \
                        or 'подтвердите, что запросы отправляли вы' in head:
                    raise YandexRealtyBlocked(
                        'Яндекс показал капчу в теле ответа.'
                    )

            return response

        # Все попытки исчерпаны.
        if last_exc:
            raise YandexRealtyError(
                f'Не удалось получить {url}: {last_exc}'
            ) from last_exc
        raise YandexRealtyError(f'Не удалось получить {url}')

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def search_by_address(
        self,
        address: dict,
        deal_type: str = 'kupit',
        property_type: str = 'kvartira',
        limit: int = 10,
    ) -> list[dict]:
        """
        Найти объявления, относящиеся к выбранному в DaData адресу.

        :param address: словарь в формате
            :func:`key.dadata.DadataClient._normalize`.
        :param deal_type: ``'kupit'`` (продажа), ``'snyat'`` (аренда).
        :param property_type: ``'kvartira'``, ``'komnata'``, ``'dom'``,
            ``'uchastok'``.
        :param limit: верхнее ограничение на количество офферов.
        :return: список словарей-кандидатов (см. :class:`YandexOffer`).
        """
        if not getattr(settings, 'YANDEX_REALTY_ENABLED', True):
            raise YandexRealtyDisabled(
                'Парсер realty.yandex.ru отключён в настройках.'
            )
        if deal_type not in {'kupit', 'snyat'}:
            raise ValueError("deal_type должен быть 'kupit' или 'snyat'")
        if property_type not in {'kvartira', 'komnata', 'dom', 'uchastok'}:
            raise ValueError(
                "property_type должен быть 'kvartira'|'komnata'|'dom'|'uchastok'"
            )

        query = self._build_query(address)
        if not query:
            return []

        self._warm_up()

        city_slug = self._city_slug(address)
        path = f'/{city_slug}/{deal_type}/{property_type}/'
        url = urljoin(BASE_URL, path)
        params = {'text': query}
        logger.info('Yandex.Realty поиск: %s ?text=%s', url, query)

        response = self._http_get(url, params=params, referer=BASE_URL + '/')
        offers = self._extract_offers_from_html(response.text)

        # Если __NEXT_DATA__ ничего не дал — пробуем общий поиск без slug.
        if not offers and city_slug != 'rossiya':
            fallback_url = urljoin(BASE_URL, '/rossiya/' + deal_type
                                   + '/' + property_type + '/')
            logger.info('Yandex.Realty fallback на /rossiya/: %s', fallback_url)
            response = self._http_get(fallback_url, params=params,
                                      referer=BASE_URL + '/')
            offers = self._extract_offers_from_html(response.text)

        return offers[:max(1, limit)]

    def parse_offer(self, offer_url: str) -> dict:
        """
        Полный разбор одного объявления по его URL.

        Возвращает словарь с полями :class:`YandexOffer`. Если URL чужой
        (не realty.yandex.ru) — выбрасывает ValueError.
        """
        if not getattr(settings, 'YANDEX_REALTY_ENABLED', True):
            raise YandexRealtyDisabled(
                'Парсер realty.yandex.ru отключён в настройках.'
            )
        if not offer_url or 'realty.yandex' not in offer_url:
            raise ValueError('URL должен указывать на realty.yandex.ru')

        self._warm_up()
        response = self._http_get(offer_url, referer=BASE_URL + '/')
        soup = BeautifulSoup(response.text, 'lxml')

        offer = YandexOffer(url=offer_url)

        # 1) самый надёжный источник — __NEXT_DATA__
        next_data = self._extract_next_data(soup)
        if next_data:
            self._fill_from_next_data(offer, next_data)

        # 2) JSON-LD дополняет/уточняет цену и адрес
        for ld in self._extract_jsonld(soup):
            self._fill_from_jsonld(offer, ld)

        # 3) OG-meta — заголовок, описание, ведущее фото
        self._fill_from_og(offer, soup)

        # 4) последний шанс — регулярки по тексту страницы
        if offer.price is None or not offer.title:
            self._fill_from_text(offer, response.text)

        return offer.to_dict()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _city_slug(address: dict) -> str:
        """Подобрать slug города из карты CITY_SLUGS."""
        candidates: list[str] = []
        for key in ('city', 'region'):
            value = (address.get(key) or '').lower()
            # У DaData 'city_with_type' = 'г Москва'. Нормализуем.
            value = re.sub(r'^(г|город|с|село|пгт|деревня|д\.|пос|поселок)\s+',
                           '', value).strip()
            if value:
                candidates.append(value)
        for cand in candidates:
            slug = CITY_SLUGS.get(cand)
            if slug:
                return slug
        return 'rossiya'

    @staticmethod
    def _build_query(address: dict) -> str:
        """
        Собрать строку поиска для Яндекса из DaData-словаря.

        Главное — улица + дом, потому что по полному адресу с квартирой
        Яндекс часто не находит ничего. Город уходит в URL-slug.
        """
        # Если есть полное unrestricted_value — используем его, обрезав
        # квартиру (она в Яндексе чаще всего лишняя для поиска).
        full = (address.get('unrestricted_value')
                or address.get('value') or '').strip()
        if full:
            full = re.sub(r',?\s*кв\.?\s*\S+\s*$', '', full,
                          flags=re.IGNORECASE)
            return full

        parts: list[str] = []
        for key in ('street_type', 'street'):
            v = (address.get(key) or '').strip()
            if v:
                parts.append(v)
        house = (address.get('house') or '').strip()
        if house:
            parts.append(house)
        block = (address.get('block') or '').strip()
        if block:
            parts.append(block)
        return ' '.join(parts)

    @staticmethod
    def _extract_next_data(soup: BeautifulSoup) -> Optional[dict]:
        """Достать содержимое <script id="__NEXT_DATA__">."""
        node = soup.find('script', id='__NEXT_DATA__')
        if not node or not node.string:
            return None
        try:
            return json.loads(node.string)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.debug('Не удалось распарсить __NEXT_DATA__: %s', exc)
            return None

    @staticmethod
    def _extract_jsonld(soup: BeautifulSoup) -> Iterable[dict]:
        """Достать все блоки <script type=application/ld+json>."""
        for node in soup.find_all('script', type='application/ld+json'):
            if not node.string:
                continue
            try:
                data = json.loads(node.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, list):
                yield from (d for d in data if isinstance(d, dict))
            elif isinstance(data, dict):
                yield data

    def _extract_offers_from_html(self, html: str) -> list[dict]:
        """
        Из HTML-страницы выдачи достать список нормализованных офферов.

        Источники, по убыванию надёжности:
            1. <script id="__NEXT_DATA__">  — структурированный JSON SPA
            2. JSON-LD блоки                 — резервный SEO-формат
            3. ссылки <a href="/.../offer/..."> — последний шанс
        """
        soup = BeautifulSoup(html, 'lxml')
        offers: list[dict] = []
        seen_urls: set[str] = set()

        # 1) __NEXT_DATA__
        nd = self._extract_next_data(soup)
        if nd:
            offers.extend(self._walk_next_data_for_offers(nd, seen_urls))

        # 2) JSON-LD
        if not offers:
            for ld in self._extract_jsonld(soup):
                items: list[dict] = []
                if ld.get('@type') in ('ItemList', 'CollectionPage'):
                    items = ld.get('itemListElement') or []
                elif ld.get('@type') in ('Apartment', 'House',
                                         'SingleFamilyResidence',
                                         'Residence', 'Product'):
                    items = [ld]
                for it in items:
                    raw = it.get('item') if isinstance(it, dict) else None
                    raw = raw or it
                    if not isinstance(raw, dict):
                        continue
                    o = YandexOffer()
                    self._fill_from_jsonld(o, raw)
                    if o.url and o.url not in seen_urls:
                        seen_urls.add(o.url)
                        offers.append(o.to_dict())

        # 3) Голые ссылки на карточки оффера
        if not offers:
            for a in soup.select('a[href*="/offer/"]'):
                href = a.get('href') or ''
                if not href:
                    continue
                full = urljoin(BASE_URL, href.split('?')[0])
                if full in seen_urls:
                    continue
                seen_urls.add(full)
                title = (a.get_text(strip=True) or '')[:200]
                offers.append(YandexOffer(url=full, title=title).to_dict())

        return offers

    def _walk_next_data_for_offers(
        self,
        data: Any,
        seen_urls: set[str],
    ) -> list[dict]:
        """
        Рекурсивно ищем словари, похожие на оффер realty.yandex.

        Эвристика: оффер содержит ``offerId``/``id`` + ``price`` +
        что-то напоминающее URL ('share', 'unsignedInternalUrl', 'url').
        Универсальный обход избавляет от хрупких путей вида
        ``props.pageProps.initialState.search.offers``, которые
        периодически переименовываются.
        """
        offers: list[dict] = []

        def is_offer_dict(d: dict) -> bool:
            keys = set(d.keys())
            has_id = bool(keys & {'offerId', 'offerID', 'id'})
            has_price = 'price' in keys or 'priceInfo' in keys
            has_url_hint = bool(
                keys & {'share', 'shareUrl', 'unsignedInternalUrl',
                        'url', 'webUrl'}
            )
            # Категория с типом «оффер» тоже сильный маркер.
            has_category = (
                d.get('category') in ('APARTMENT', 'ROOMS', 'HOUSE', 'LOT')
                or d.get('offerCategory') in ('APARTMENT', 'ROOMS', 'HOUSE')
            )
            return has_id and (has_price or has_category) and (
                has_url_hint or has_category
            )

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if is_offer_dict(node):
                    offer = YandexRealtyParser._offer_from_next_dict(node)
                    if offer.url and offer.url not in seen_urls:
                        seen_urls.add(offer.url)
                        offers.append(offer.to_dict())
                    # внутрь оффера тоже идём, но с пониженным
                    # приоритетом — там встречаются вложенные похожие.
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for v in node:
                    visit(v)

        visit(data)
        return offers

    @staticmethod
    def _offer_from_next_dict(d: dict) -> YandexOffer:
        """Сконструировать YandexOffer из словаря __NEXT_DATA__."""
        offer = YandexOffer()
        offer.raw_id = str(
            d.get('offerId') or d.get('offerID') or d.get('id') or ''
        ) or None

        # URL
        share = d.get('shareUrl') or d.get('share') \
            or d.get('unsignedInternalUrl') or d.get('url') or d.get('webUrl')
        if share:
            offer.url = share if share.startswith('http') \
                else urljoin(BASE_URL, share)
        elif offer.raw_id:
            # Жёсткий fallback — собираем «по шаблону».
            offer.url = f'{BASE_URL}/offer/{offer.raw_id}/'

        # Цена
        price_info = d.get('price') if isinstance(d.get('price'), dict) \
            else d.get('priceInfo') or {}
        if isinstance(price_info, dict):
            value = (price_info.get('value') or price_info.get('rawValue')
                     or price_info.get('price'))
            offer.price = YandexRealtyParser._safe_float(value)
            offer.currency = price_info.get('currency') or 'RUB'
            ppm = price_info.get('pricePerM2') or price_info.get('unitPrice')
            offer.price_per_sqm = YandexRealtyParser._safe_float(ppm)

        # Площади/комнаты/этаж
        area = d.get('area') if isinstance(d.get('area'), dict) else None
        if area:
            offer.area_total = YandexRealtyParser._safe_float(area.get('value'))
        living = d.get('livingArea') if isinstance(d.get('livingArea'), dict) else None
        if living:
            offer.area_living = YandexRealtyParser._safe_float(living.get('value'))
        kitchen = d.get('kitchenArea') if isinstance(d.get('kitchenArea'), dict) else None
        if kitchen:
            offer.area_kitchen = YandexRealtyParser._safe_float(kitchen.get('value'))

        rooms = d.get('roomsTotal') or d.get('rooms') or d.get('roomsCount')
        if isinstance(rooms, (int, float)):
            offer.rooms_count = int(rooms)
        floor = d.get('floorNumber') or d.get('floor')
        if isinstance(floor, (int, float)):
            offer.floor_number = int(floor)
        floors = d.get('floorsTotal') or d.get('floorsCount')
        if isinstance(floors, (int, float)):
            offer.total_floors = int(floors)

        # Адрес/координаты
        location = d.get('location') if isinstance(d.get('location'), dict) else {}
        if location:
            offer.address = (location.get('address')
                             or location.get('geocoderAddress') or '') or offer.address
            point = location.get('point') if isinstance(location.get('point'), dict) else {}
            offer.geo_lat = YandexRealtyParser._safe_float(point.get('latitude') or point.get('lat'))
            offer.geo_lon = YandexRealtyParser._safe_float(point.get('longitude') or point.get('lon'))

        # Описание/заголовок
        offer.title = (d.get('appLargeSnippetTitle')
                       or d.get('title') or offer.address or offer.title)
        offer.description = d.get('description') or offer.description

        # Фотографии
        photos = d.get('photos') or d.get('images') or []
        urls: list[str] = []
        if isinstance(photos, list):
            for p in photos:
                if isinstance(p, str):
                    urls.append(YandexRealtyParser._normalize_photo_url(p))
                elif isinstance(p, dict):
                    candidate = (p.get('full') or p.get('large')
                                 or p.get('xxl') or p.get('xl')
                                 or p.get('url') or p.get('viewUrl'))
                    if candidate:
                        urls.append(YandexRealtyParser._normalize_photo_url(candidate))
        offer.photos = [u for u in urls if u]

        # Тип сделки/недвижимости
        offer_type = (d.get('offerType') or '').lower()
        if 'rent' in offer_type:
            offer.deal_type = 'rent'
        elif 'sell' in offer_type:
            offer.deal_type = 'sell'
        category = (d.get('category') or d.get('offerCategory') or '').lower()
        if category:
            offer.property_type = category

        return offer

    @staticmethod
    def _fill_from_next_data(offer: YandexOffer, data: dict) -> None:
        """Заполнить YandexOffer из __NEXT_DATA__ страницы оффера."""
        # Структура страницы оффера: data["props"]["pageProps"]["card"]
        # либо ["offerCard"], в зависимости от версии. Идём широким
        # обходом и берём первый словарь, у которого выглядит
        # «как карточка одного оффера».
        target: Optional[dict] = None

        def visit(node: Any) -> None:
            nonlocal target
            if target is not None:
                return
            if isinstance(node, dict):
                if {'offerId', 'price'}.issubset(node.keys()) \
                        or {'id', 'price', 'location'}.issubset(node.keys()):
                    target = node
                    return
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for v in node:
                    visit(v)

        visit(data)
        if not target:
            return
        filled = YandexRealtyParser._offer_from_next_dict(target)
        # Перенесём непустые поля в исходный offer.
        for k, v in filled.to_dict().items():
            if k == 'source':
                continue
            cur = getattr(offer, k, None)
            if v in (None, '', [], 0) and cur not in (None, '', [], 0):
                continue
            if cur in (None, '', [], 0) or k == 'photos':
                if k == 'photos' and offer.photos:
                    # объединяем уникально, сохраняя порядок
                    existing = set(offer.photos)
                    offer.photos = offer.photos + [u for u in v if u not in existing]
                else:
                    setattr(offer, k, v)

    @staticmethod
    def _fill_from_jsonld(offer: YandexOffer, ld: dict) -> None:
        """Заполнить YandexOffer из блока JSON-LD."""
        type_ = ld.get('@type') or ''
        if isinstance(type_, list):
            type_ = type_[0] if type_ else ''
        # Цена
        offers_field = ld.get('offers')
        if isinstance(offers_field, dict):
            price = offers_field.get('price') or offers_field.get('lowPrice')
            currency = offers_field.get('priceCurrency')
            if price and offer.price is None:
                offer.price = YandexRealtyParser._safe_float(price)
            if currency and not offer.currency:
                offer.currency = currency
        # Адрес
        addr = ld.get('address')
        if isinstance(addr, dict) and not offer.address:
            offer.address = (addr.get('streetAddress')
                             or addr.get('addressLocality') or '')
        # Гео
        geo = ld.get('geo')
        if isinstance(geo, dict):
            if offer.geo_lat is None:
                offer.geo_lat = YandexRealtyParser._safe_float(geo.get('latitude'))
            if offer.geo_lon is None:
                offer.geo_lon = YandexRealtyParser._safe_float(geo.get('longitude'))
        # Площадь
        floor_size = ld.get('floorSize')
        if isinstance(floor_size, dict) and offer.area_total is None:
            offer.area_total = YandexRealtyParser._safe_float(floor_size.get('value'))
        # Описание/заголовок
        if not offer.title and ld.get('name'):
            offer.title = ld['name']
        if not offer.description and ld.get('description'):
            offer.description = ld['description']
        # Фото
        image = ld.get('image')
        if image:
            if isinstance(image, str):
                if image not in offer.photos:
                    offer.photos.append(image)
            elif isinstance(image, list):
                for u in image:
                    if isinstance(u, str) and u not in offer.photos:
                        offer.photos.append(u)
        # URL
        if not offer.url and ld.get('url'):
            offer.url = ld['url']

    @staticmethod
    def _fill_from_og(offer: YandexOffer, soup: BeautifulSoup) -> None:
        """Заполнить из Open Graph / стандартных meta-тегов."""
        def meta(prop: str) -> str:
            node = soup.find('meta', attrs={'property': prop})
            if node and node.get('content'):
                return node['content'].strip()
            node = soup.find('meta', attrs={'name': prop})
            if node and node.get('content'):
                return node['content'].strip()
            return ''

        if not offer.title:
            offer.title = meta('og:title') or (
                soup.title.string.strip() if soup.title and soup.title.string else ''
            )
        if not offer.description:
            offer.description = meta('og:description') or meta('description')
        og_image = meta('og:image')
        if og_image and og_image not in offer.photos:
            offer.photos.insert(0, og_image)

    @staticmethod
    def _fill_from_text(offer: YandexOffer, html: str) -> None:
        """Регулярные выражения как самый последний fallback."""
        if offer.price is None:
            m = re.search(r'"price"\s*:\s*\{\s*"value"\s*:\s*([\d.]+)', html)
            if m:
                offer.price = YandexRealtyParser._safe_float(m.group(1))
        if not offer.title:
            m = re.search(r'<title>([^<]{5,200})</title>', html, re.IGNORECASE)
            if m:
                offer.title = m.group(1).strip()

    @staticmethod
    def _normalize_photo_url(url: str) -> str:
        """
        Привести URL фото Яндекса к http(s).

        Часто Яндекс отдаёт ссылки в виде ``//avatars.mds.yandex.net/...``
        — без протокола. В таких случаях добавляем ``https:``.
        """
        if not url:
            return ''
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return urljoin(BASE_URL, url)
        return url

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            v = value.replace(' ', '').replace(',', '.')
            try:
                return float(v)
            except ValueError:
                return None
        return None
