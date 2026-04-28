# РИЭЛТ — учётная система агентства недвижимости (Django + Vue)

CRM/ERP-шаблон для агентства недвижимости: Django 6 + DRF на бэкенде,
Vue 3 + Pinia + Vite на фронтенде, PostgreSQL в качестве хранилища,
подсказки адресов — DaData (через открытый ключ), авторизация — JWT.

## Суть CRM/ERP в этом проекте

Система строится по классической модели агентства недвижимости:

- **CRM-контур (работа с клиентами).** Пользователи → заявки → показы →
  сделки. Клиент регистрируется самостоятельно, но без выбора роли.
  Тип учётной записи и должность назначает администратор или менеджер
  через отдельный эндпоинт и интерфейс. У клиента свой «вид» данных —
  он видит только свои заявки, сделки и просмотры.
- **ERP-контур (внутренняя работа агентства).** Объекты недвижимости,
  их статусы и история изменений, документы, фотографии, характеристики,
  воронка сделок (статусы: «открыта» → «переговоры» → «договор» →
  «завершена» / «отменена»), а также задачи сотрудников (звонок, показ,
  документы) с приоритетами, исполнителями и сроками.
- **Разделение прав.** Три роли сотрудников — администратор, менеджер,
  агент. Агент работает только со своими заявками/задачами;
  администратор и менеджер видят всё и распоряжаются назначениями.
  Клиент — только «свой» срез данных.

## Структура

```
simple/
├── manage.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
│
├── simple/                              ← Django-проект
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── key/                                 ← Django-приложение CRM/ERP
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── business_rules.py
│   ├── dadata.py
│   ├── deals_service.py
│   ├── documents.py
│   ├── events.py
│   ├── kpi.py
│   ├── mailing.py
│   ├── models.py
│   ├── permissions.py
│   ├── serializers.py
│   ├── signals.py
│   ├── task_actions.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── yandex_realty.py
│   ├── fonts/
│   │   ├── DejaVuSans.ttf
│   │   └── DejaVuSans-Bold.ttf
│   ├── management/
│   │   └── commands/
│   │       ├── seed_demo.py
│   │       └── seed_dictionaries.py
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py
│   └── templatetags/
│       ├── __init__.py
│       └── vite.py
│
├── templates/                           ← HTML/email-шаблоны
│   ├── index.html
│   └── emails/
│       ├── property_matched/            ← body.html, body.txt, subject.txt
│       ├── request_closed/              ← body.txt, subject.txt
│       ├── request_taken/               ← body.txt, subject.txt
│       ├── task_assigned/               ← body.txt, subject.txt
│       ├── task_assigned_call/          ← body.txt, subject.txt
│       ├── task_assigned_documents/     ← body.txt, subject.txt
│       └── task_assigned_showing/       ← body.txt, subject.txt
│
└── frontend/                            ← Vue 3 + Vite SPA
    ├── index.html
    ├── package.json
    ├── package-lock.json
    ├── pnpm-lock.yaml
    ├── vite.config.js
    └── src/
        ├── App.vue
        ├── main.js
        ├── router.js
        ├── api/
        │   ├── index.js
        │   └── tasks.js
        ├── components/
        │   ├── AddressAutocomplete.vue
        │   ├── AppFooter.vue
        │   ├── CurrentTaskWidget.vue
        │   ├── InfoRow.vue
        │   ├── PropertyCard.vue
        │   ├── StatCard.vue
        │   ├── TaskMineBadge.vue
        │   ├── ToastHost.vue
        │   ├── TopBar.vue
        │   └── YandexRealtyImport.vue
        ├── store/
        │   ├── auth.js
        │   ├── toasts.js
        │   └── workload.js
        ├── styles/
        │   └── main.css
        ├── utils/
        │   └── formatters.js
        └── views/
            ├── Account.vue
            ├── Admin.vue
            ├── Clients.vue
            ├── Dashboard.vue
            ├── Deals.vue
            ├── Login.vue
            ├── Properties.vue
            ├── PropertyDetail.vue
            ├── PropertyForm.vue
            ├── Register.vue
            ├── RequestDetail.vue
            ├── Requests.vue
            ├── TaskWorkflow.vue
            └── Tasks.vue
```

## Почему именно так

- **Папка проекта `simple`, приложение `key`** — сохранены из исходной
  структуры, менять названия пакетов не требуется.
- **3НФ-схема БД** реализована на уровне Django-моделей
  (`key/models.py`) с явными именами таблиц в `Meta.db_table`.
  `python manage.py migrate` строит таблицы один в один.
- **Кастомная модель пользователя** (`AbstractBaseUser` + `PermissionsMixin`)
  нужна, потому что в проекте есть `user_type`, `phone`,
  `is_email_verified`, `role` и т. п.
- **JWT (`djangorestframework-simplejwt`)** — токен-аутентификация
  с ротацией и чёрным списком refresh-токенов.
- **Подсказки адресов — DaData.** Ключ хранится только в `.env`
  на сервере, клиент обращается к прокси-эндпоинту
  `/api/dadata/suggest-address/`. Изображения и характеристики объектов
  вводятся сотрудником вручную — DaData даёт только адресные данные.
- **Автозаполнение карточки — парсер `realty.yandex.ru`.** После выбора
  адреса в подсказках DaData сотрудник может одним нажатием подтянуть
  цену, площади, описание и фотографии похожего объявления с
  Яндекс.Недвижимости. Парсер ходит только серверным запросом
  (`/api/yandex-realty/search/` и `/api/yandex-realty/import/`),
  с рандомными паузами между запросами и ротацией User-Agent —
  чтобы не получить капчу. Все подставленные значения остаются
  редактируемыми, прежде чем попасть в БД через обычный
  `POST /api/properties/`.
- **Регистрация без выбора роли.** `RegisterSerializer` принимает только
  `username`, `email`, `phone`, `password`, и всегда создаёт клиента
  без должности. Назначение роли делает администратор или менеджер
  через `/api/users/{id}/assign_role/`.
- **`django-vite`** подключает сборку Vue как обычный статический ассет,
  сохраняя single-project / single-template схему.

## Запуск

### 1. Бэкенд

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # заполните креды PostgreSQL и DADATA_API_KEY
createdb re_crm                      # или через pgAdmin / psql

python manage.py migrate
python manage.py seed_dictionaries   # наполнение справочников
python manage.py createsuperuser
python manage.py runserver
```

Админка: http://127.0.0.1:8000/admin/

### 2. Фронтенд

```bash
cd frontend
npm install
npm run dev                           # Vite dev-сервер на :5173 с HMR
```

Открываем **http://127.0.0.1:8000/** — Django отдаёт шаблон,
а `{% vite_asset %}` подключает модули с dev-сервера Vite.

### 3. Сборка под прод

```bash
cd frontend && npm run build
# в .env выставить DJANGO_VITE_DEV_MODE=False
python manage.py collectstatic --noinput
```

## API (основное)

| Метод | URL                                         | Описание                                      |
|-------|---------------------------------------------|-----------------------------------------------|
| POST  | `/api/auth/register/`                       | Регистрация (всегда клиент, без роли)         |
| POST  | `/api/auth/login/`                          | Логин → `{access, refresh}`                   |
| POST  | `/api/auth/refresh/`                        | Обновление `access`                           |
| GET   | `/api/auth/me/`                             | Текущий пользователь                          |
| GET   | `/api/dadata/suggest-address/?q=...`        | Подсказки адресов через DaData                |
| POST  | `/api/yandex-realty/search/`                | Поиск похожих объявлений на realty.yandex.ru  |
| POST  | `/api/yandex-realty/import/`                | Разбор конкретного объявления по URL          |
| CRUD  | `/api/users/`                               | Пользователи (список для сотрудников)         |
| POST  | `/api/users/{id}/assign_role/`              | Назначить тип и должность (админ/менеджер)    |
| CRUD  | `/api/properties/`                          | Объекты недвижимости                          |
| POST  | `/api/properties/{id}/change_status/`       | Смена статуса + запись в историю              |
| POST  | `/api/properties/{id}/upload_photo/`        | Загрузка фото (файл или внешняя ссылка)       |
| GET   | `/api/properties/{id}/history/`             | История статусов                              |
| CRUD  | `/api/property-photos/`                     | Фото объектов                                 |
| CRUD  | `/api/property-features/`                   | Справочник характеристик                      |
| CRUD  | `/api/requests/`                            | Заявки клиентов                               |
| POST  | `/api/requests/{id}/close/`                 | Закрыть заявку                                |
| CRUD  | `/api/deals/`                               | Сделки                                        |
| POST  | `/api/deals/{id}/change_status/`            | Смена статуса сделки (воронка)                |
| CRUD  | `/api/tasks/`                               | Задачи сотрудников                            |
| POST  | `/api/tasks/{id}/change_status/`            | Смена статуса задачи                          |
| POST  | `/api/tasks/{id}/complete/`                 | Быстро пометить задачу как выполненную        |
| CRUD  | `/api/cities/`, `/api/streets/`, `/api/houses/`, `/api/addresses/` | Адресная иерархия |
| GET   | `/api/dashboard/stats/`                     | Сводка для главного экрана                    |

## Парсер Yandex.Realty (автозаполнение карточки)

Чтобы сотрудник не вбивал каждое поле объекта вручную, в проекте есть
тонкий серверный парсер `realty.yandex.ru` (`key/yandex_realty.py`).
Он используется только из формы создания/редактирования объекта,
**после** того как адрес выбран в подсказках DaData.

**Как это работает:**

1. На фронте сотрудник выбирает адрес в `AddressAutocomplete`.
2. Виджет `YandexRealtyImport.vue` отправляет
   `POST /api/yandex-realty/search/` с этим адресом и фильтрами
   (продажа/аренда, тип объекта).
3. Сервер собирает поисковый URL Яндекса по slug-ам городов
   (`CITY_SLUGS`), делает один HTTP-запрос с реалистичными заголовками,
   парсит блок `<script id="__NEXT_DATA__">` (с fallback-ами на JSON-LD
   и OG-теги) и возвращает список нормализованных предложений.
4. Сотрудник выбирает подходящее, фронт дёргает
   `POST /api/yandex-realty/import/` с URL объявления — приходит
   полный разбор (цена, площади, описание, фото).
5. Поля формы заполняются только в тех местах, где сотрудник
   ещё ничего не ввёл. Фотографии добавляются как внешние URL;
   при сохранении объекта они уезжают в `/api/property-photos/`
   через штатную ветку с полем `url`.

**Защита от банов и капчи:**

- Между запросами выдерживается случайная пауза
  `[YANDEX_REALTY_MIN_DELAY; YANDEX_REALTY_MAX_DELAY]` секунд
  (по умолчанию 2..5 — щадящий режим).
- Перед первым «живым» запросом сессия «прогревается» обращением
  к корню сайта, чтобы получить базовые куки.
- На каждый запрос ротируется `User-Agent` из набора реальных
  браузеров; ставятся `Sec-Fetch-*`, `Accept-Language` и т.д.
- Если Яндекс показал капчу или вернул 403/429, парсер выбрасывает
  `YandexRealtyBlocked`, которая на уровне view превращается в
  HTTP 503 — фронт показывает понятное сообщение «попробуйте позже».
- Можно прозрачно подключить HTTP-прокси через
  `YANDEX_REALTY_PROXY_URL` (поддерживается формат
  `http://user:pass@host:port`).
- Парсер можно полностью выключить флагом
  `YANDEX_REALTY_ENABLED=False` — это превращает обе ручки в HTTP 503.

**Переменные окружения парсера:**

| Переменная | Назначение | По умолчанию |
|------------|------------|--------------|
| `YANDEX_REALTY_ENABLED` | Включить/выключить парсер | `True` |
| `YANDEX_REALTY_MIN_DELAY` | Нижняя граница паузы между запросами, сек | `2.0` |
| `YANDEX_REALTY_MAX_DELAY` | Верхняя граница паузы, сек | `5.0` |
| `YANDEX_REALTY_TIMEOUT` | Таймаут HTTP-запроса, сек | `20.0` |
| `YANDEX_REALTY_DEFAULT_LIMIT` | Макс. число офферов в поиске | `10` |
| `YANDEX_REALTY_PROXY_URL` | Прокси, если IP уже забанен | `''` |

Юнит-тесты парсера лежат в `key/tests.py` — гоняются как
`python manage.py test key`.

## Безопасность

- Ключ DaData живёт **только в `.env`** на сервере, в заголовок
  `Authorization: Token <api-key>` подставляется на серверной стороне.
- Пароли хешируются PBKDF2 (стандарт Django).
- Доступ к защищённым эндпоинтам — только с действующим JWT.
- Разграничение прав: сотрудник редактирует, клиент только читает
  собственные данные, назначать должности может только администратор
  или менеджер.
- CORS ограничен доверенными origins.

## Назначение файлов

### Корень

- **manage.py** — точка входа Django CLI.
- **requirements.txt** — зависимости Python.
- **.env.example** — шаблон переменных окружения.
- **.gitignore** — исключения для git.
- **README.md** — этот файл.

### `simple/` (Django-проект)

- **__init__.py** — маркер пакета.
- **settings.py** — настройки Django (БД, приложения, middleware).
- **urls.py** — корневой роутер URL.
- **asgi.py** — ASGI-точка входа.
- **wsgi.py** — WSGI-точка входа.

### `key/` (приложение CRM)

- **__init__.py** — маркер пакета.
- **admin.py** — регистрация моделей в Django-admin.
- **apps.py** — конфиг приложения.
- **business_rules.py** — бизнес-правила (валидации, расчёты).
- **dadata.py** — клиент сервиса подсказок DaData.
- **deals_service.py** — сервис создания и закрытия сделок.
- **documents.py** — генерация PDF-договоров через ReportLab.
- **events.py** — журнал доменных событий.
- **kpi.py** — расчёт KPI агентов.
- **mailing.py** — отправка email-уведомлений.
- **models.py** — ORM-модели (User, Property, Request, Deal, Task и т. д.).
- **permissions.py** — DRF-пермишены по ролям.
- **serializers.py** — DRF-сериализаторы.
- **signals.py** — Django-сигналы (post_save и пр.).
- **task_actions.py** — операции над задачами (старт/пауза/завершение).
- **tests.py** — модульные тесты.
- **urls.py** — URL-роутер приложения.
- **views.py** — DRF ViewSet'ы и API-эндпоинты.
- **yandex_realty.py** — парсер объявлений `realty.yandex.ru` для
  автозаполнения карточки объекта. Тротлинг, ротация User-Agent,
  детекция CAPTCHA, разбор `__NEXT_DATA__`/JSON-LD/OG-meta.
- **fonts/DejaVuSans.ttf**, **DejaVuSans-Bold.ttf** — шрифты с кириллицей для PDF.
- **management/commands/seed_demo.py** — заполнение демо-данными.
- **management/commands/seed_dictionaries.py** — заполнение справочников.
- **migrations/0001_initial.py** — начальная миграция схемы БД.
- **templatetags/vite.py** — теги шаблонов для подключения Vite-бандла.

### `templates/`

- **index.html** — корневой HTML, в который монтируется SPA.
- **emails/property_matched/** — письмо клиенту: подобран объект.
- **emails/request_closed/** — письмо: заявка закрыта.
- **emails/request_taken/** — письмо: заявку взяли в работу.
- **emails/task_assigned/** — письмо: назначена задача (общее).
- **emails/task_assigned_call/** — назначен звонок.
- **emails/task_assigned_documents/** — назначены документы.
- **emails/task_assigned_showing/** — назначен показ.
- В каждой папке: **subject.txt** — тема, **body.txt** — текстовая версия, **body.html** — HTML-версия (если есть).

### `frontend/` (корень SPA)

- **index.html** — HTML-точка входа Vite.
- **package.json**, **package-lock.json**, **pnpm-lock.yaml** — манифест и лок-файлы зависимостей.
- **vite.config.js** — конфиг сборки Vite (alias, прокси).

### `frontend/src/`

- **App.vue** — корневой компонент SPA.
- **main.js** — bootstrap Vue/Pinia/Router.
- **router.js** — описание маршрутов.

### `frontend/src/api/`

- **index.js** — axios-инстанс и общие CRUD-эндпоинты.
- **tasks.js** — API задач (старт/пауза/завершение).

### `frontend/src/components/`

- **AddressAutocomplete.vue** — поле адреса с подсказками DaData.
- **AppFooter.vue** — подвал приложения.
- **CurrentTaskWidget.vue** — виджет текущей активной задачи.
- **InfoRow.vue** — строка «label — value» для деталей.
- **PropertyCard.vue** — карточка объекта недвижимости.
- **StatCard.vue** — карточка с числовым показателем.
- **TaskMineBadge.vue** — бейдж «моя задача».
- **ToastHost.vue** — контейнер для toast-уведомлений.
- **TopBar.vue** — верхняя навигационная панель.
- **YandexRealtyImport.vue** — виджет автозаполнения карточки объекта
  данными с realty.yandex.ru: поиск похожих объявлений по адресу
  DaData, импорт по URL, подстановка пустых полей формы и фото.

### `frontend/src/store/`

- **auth.js** — авторизация, токен, профиль пользователя.
- **toasts.js** — очередь toast-уведомлений.
- **workload.js** — текущая нагрузка агента (активные задачи).

### `frontend/src/styles/`

- **main.css** — глобальные стили и CSS-переменные.

### `frontend/src/utils/`

- **formatters.js** — общие форматтеры денег и дат.

### `frontend/src/views/`

- **Account.vue** — личный кабинет пользователя.
- **Admin.vue** — административная панель.
- **Clients.vue** — список клиентов.
- **Dashboard.vue** — главная со сводкой и KPI.
- **Deals.vue** — список сделок.
- **Login.vue** — страница входа.
- **Properties.vue** — каталог объектов.
- **PropertyDetail.vue** — детальная карточка объекта.
- **PropertyForm.vue** — форма создания/редактирования объекта.
- **Register.vue** — регистрация.
- **RequestDetail.vue** — детальная карточка заявки.
- **Requests.vue** — список заявок.
- **TaskWorkflow.vue** — пошаговое выполнение задачи.
- **Tasks.vue** — список задач агента.
