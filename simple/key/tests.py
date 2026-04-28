"""
Тесты приложения ``key``.

Покрывают только ту функциональность, которую можно проверить без
реальных внешних сервисов (DaData, realty.yandex.ru): парсинг HTML с
синтетическим ``__NEXT_DATA__`` и нормализация полей.
"""
from __future__ import annotations

import json

from django.test import SimpleTestCase

from .yandex_realty import YandexRealtyParser, YandexOffer


class YandexRealtyParserTests(SimpleTestCase):
    """Юниты на чистые функции парсера realty.yandex.ru."""

    def test_city_slug_known(self):
        p = YandexRealtyParser()
        self.assertEqual(p._city_slug({'city': 'г Москва'}), 'moskva')
        self.assertEqual(p._city_slug({'city': 'Санкт-Петербург'}),
                         'sankt-peterburg')

    def test_city_slug_unknown_falls_back_to_rossiya(self):
        p = YandexRealtyParser()
        self.assertEqual(p._city_slug({'city': 'г Урюпинск'}), 'rossiya')

    def test_build_query_strips_apartment_from_value(self):
        """Квартира из адреса DaData в поисковый запрос не уходит."""
        p = YandexRealtyParser()
        addr = {
            'value': 'г Москва, ул Ленина, д 5, кв 12',
            'unrestricted_value': 'г Москва, ул Ленина, д 5, кв 12',
        }
        self.assertEqual(p._build_query(addr), 'г Москва, ул Ленина, д 5')

    def test_build_query_assembles_from_parts(self):
        p = YandexRealtyParser()
        addr = {'street_type': 'ул', 'street': 'Ленина', 'house': '5'}
        self.assertEqual(p._build_query(addr), 'ул Ленина 5')

    def test_safe_float_handles_russian_decimal(self):
        self.assertEqual(YandexRealtyParser._safe_float('1 234,56'), 1234.56)
        self.assertIsNone(YandexRealtyParser._safe_float('abc'))
        self.assertEqual(YandexRealtyParser._safe_float(42), 42.0)

    def test_normalize_photo_url_adds_protocol(self):
        url = YandexRealtyParser._normalize_photo_url(
            '//avatars.mds.yandex.net/test'
        )
        self.assertEqual(url, 'https://avatars.mds.yandex.net/test')

    def test_extract_offers_from_html_parses_next_data(self):
        """Список офферов из __NEXT_DATA__ должен быть распознан."""
        next_data = {
            'props': {
                'pageProps': {
                    'searchResults': {
                        'offers': [
                            {
                                'offerId': '111',
                                'price': {'value': 9500000, 'currency': 'RUB',
                                          'pricePerM2': 200000},
                                'shareUrl': '/offer/111/',
                                'roomsTotal': 2,
                                'floorNumber': 4,
                                'floorsTotal': 9,
                                'area': {'value': 47.5},
                                'location': {
                                    'address': 'Москва, ул Ленина, 5',
                                    'point': {'latitude': 55.75,
                                              'longitude': 37.61},
                                },
                                'photos': [{'full': '//im/photo-1.jpg'}],
                                'category': 'APARTMENT',
                            },
                        ],
                    },
                },
            },
        }
        html = (
            '<html><head></head><body>'
            f'<script id="__NEXT_DATA__" type="application/json">'
            f'{json.dumps(next_data)}</script>'
            '</body></html>'
        )
        p = YandexRealtyParser()
        offers = p._extract_offers_from_html(html)
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer['raw_id'], '111')
        self.assertEqual(offer['price'], 9500000.0)
        self.assertEqual(offer['rooms_count'], 2)
        self.assertEqual(offer['floor_number'], 4)
        self.assertEqual(offer['total_floors'], 9)
        self.assertEqual(offer['area_total'], 47.5)
        self.assertTrue(offer['url'].endswith('/offer/111/'))
        self.assertIn('https://im/photo-1.jpg', offer['photos'])

    def test_extract_offers_from_jsonld_when_no_next_data(self):
        """Если __NEXT_DATA__ нет — fallback на JSON-LD."""
        ld = {
            '@type': 'Apartment',
            'name': 'Двушка на Ленина',
            'description': 'Хорошая квартира',
            'url': 'https://realty.yandex.ru/offer/222/',
            'image': ['https://im/a.jpg', 'https://im/b.jpg'],
            'offers': {'price': 8800000, 'priceCurrency': 'RUB'},
            'address': {'streetAddress': 'ул Ленина, 5'},
            'geo': {'latitude': 55.75, 'longitude': 37.61},
            'floorSize': {'value': 47},
        }
        html = (
            '<html><body>'
            f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            '</body></html>'
        )
        p = YandexRealtyParser()
        offers = p._extract_offers_from_html(html)
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer['title'], 'Двушка на Ленина')
        self.assertEqual(offer['price'], 8800000.0)
        self.assertEqual(offer['url'], 'https://realty.yandex.ru/offer/222/')
        self.assertEqual(offer['area_total'], 47.0)
        self.assertEqual(offer['geo_lat'], 55.75)
        self.assertEqual(len(offer['photos']), 2)
