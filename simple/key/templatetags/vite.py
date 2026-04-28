# key/templatetags/vite.py
"""
Шаблонный тег `{% vite_asset 'src/main.js' %}`.

Понимает два режима работы:

* **DEV (`DJANGO_VITE['default']['dev_mode'] = True`)** — подключает
  `http://host:port/@vite/client` (HMR) и сам входной модуль с
  vite-dev-сервера. Используется во время разработки, когда
  фронтенд запущен `npm run dev`.

* **PROD** — читает `frontend/dist/.vite/manifest.json`, собранный
  командой `npm run build`, и рендерит `<link>` для CSS-чанков
  плюс `<script type="module">` для JS-чанков с реальными
  hash-именами файлов.

Особенности реализации:

* В режиме `DEBUG=True` manifest **никогда не кешируется**: после
  каждого `npm run build` тэг автоматически отдаёт новые хеши без
  перезапуска `runserver`. Раньше из-за модульного кеша после
  пересборки страница продолжала ссылаться на удалённые чанки
  (`Admin-<hash>.js → 404`).
* В проде manifest читается один раз и держится в памяти —
  это безопасно, потому что в проде статика собирается до старта
  процесса и не меняется во время работы.
* Если manifest отсутствует или повреждён, тэг возвращает HTML-
  комментарий с понятным указанием, что делать дальше — это
  гораздо удобнее «молчаливого» 500 от Django.
"""
from __future__ import annotations

import json
from pathlib import Path

from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

register = template.Library()

_manifest_cache: dict | None = None


def _vite_settings() -> dict:
    """Достаём конфиг django-vite, не падая, если его нет."""
    cfg = getattr(settings, 'DJANGO_VITE', {}) or {}
    return cfg.get('default', {}) if isinstance(cfg, dict) else {}


def _manifest_path() -> Path:
    """Путь до Vite-манифеста.

    В первую очередь берём из `DJANGO_VITE['default']['manifest_path']`,
    как fallback — `settings.VITE_ASSETS_DIR / manifest.json`.
    """
    cfg = _vite_settings()
    if cfg.get('manifest_path'):
        return Path(cfg['manifest_path'])
    base = getattr(settings, 'VITE_ASSETS_DIR', None)
    if base:
        return Path(base) / 'manifest.json'
    # последний шанс — стандартное расположение
    return Path(settings.BASE_DIR) / 'frontend' / 'dist' / '.vite' / 'manifest.json'


def _load_manifest() -> dict:
    """Читаем manifest. В DEBUG не кешируем — чтобы пересборка
    фронта подхватывалась без перезапуска runserver."""
    global _manifest_cache
    if not getattr(settings, 'DEBUG', False) and _manifest_cache is not None:
        return _manifest_cache

    manifest_file = _manifest_path()
    if not manifest_file.exists():
        raise FileNotFoundError(
            f"Vite manifest not found: {manifest_file}. "
            "Соберите фронтенд командой `npm run build` в каталоге frontend/."
        )
    with manifest_file.open('r', encoding='utf-8') as f:
        data = json.load(f)

    if not getattr(settings, 'DEBUG', False):
        _manifest_cache = data
    return data


def _dev_tags(entry: str) -> str:
    """HTML для подключения vite-dev-сервера."""
    cfg = _vite_settings()
    host = cfg.get('dev_server_host', '127.0.0.1')
    port = cfg.get('dev_server_port', 5173)
    base = f'http://{host}:{port}'
    return (
        f'<script type="module" src="{base}/@vite/client"></script>\n'
        f'<script type="module" src="{base}/{entry.lstrip("/")}"></script>'
    )


def _prod_tags(entry: str) -> str:
    """HTML для production-сборки на основе Vite-манифеста."""
    try:
        manifest = _load_manifest()
    except Exception as exc:
        return (
            f'<!-- Vite manifest error: {exc}. '
            'Запустите `npm run build` в каталоге frontend/. -->'
        )

    # Vite пишет ключ как 'src/main.js' (без ведущего слеша).
    key = entry.lstrip('/')
    if key not in manifest:
        return (
            f'<!-- Vite manifest has no entry "{key}". '
            f'Проверьте rollupOptions.input в frontend/vite.config.js. -->'
        )

    data = manifest[key]
    static_prefix = settings.STATIC_URL.rstrip('/')

    tags: list[str] = []
    # CSS, импортированный из этого entry
    for css in data.get('css', []) or []:
        href = f"{static_prefix}/{css.lstrip('/')}"
        tags.append(f'<link rel="stylesheet" href="{href}">')
    # Сам JS-входник
    js = data.get('file')
    if js:
        src = f"{static_prefix}/{js.lstrip('/')}"
        tags.append(f'<script type="module" src="{src}"></script>')
    # Modulepreload для импортируемых чанков, чтобы lazy-роуты
    # подгружались без задержки и без 404 при медленной сети.
    for imp in data.get('imports', []) or []:
        chunk = manifest.get(imp) or {}
        chunk_file = chunk.get('file')
        if chunk_file:
            href = f"{static_prefix}/{chunk_file.lstrip('/')}"
            tags.append(f'<link rel="modulepreload" href="{href}">')

    return '\n'.join(tags)


@register.simple_tag
def vite_asset(entry: str):
    """Подключить Vite-входник `entry` (например, `src/main.js`)."""
    cfg = _vite_settings()
    if cfg.get('dev_mode'):
        return mark_safe(_dev_tags(entry))
    return mark_safe(_prod_tags(entry))
