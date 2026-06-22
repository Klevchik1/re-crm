"""
Клиент SmartPay (SberDevices).

Документация: https://developers.sber.ru/docs/ru/va/about/monetization/payments
Базовый URL: https://smartpay.devices.sberbank.ru/smartpay/v1/

Авторизация: Bearer-токен в заголовке Authorization.
Тестовый токен работает в боевой среде, сумма платежа ≤ 1 ₽.

Используется из viewing_payments.py для создания и проверки счётов
при записи на просмотр объекта недвижимости.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SMARTPAY_BASE_URL = "https://smartpay.devices.sberbank.ru/smartpay/v1"


class SmartPayError(Exception):
    """Ошибка при работе со SmartPay API."""


def _get_headers() -> dict[str, str]:
    token = getattr(settings, "SMARTPAY_TOKEN", "")
    if not token:
        raise SmartPayError(
            "SMARTPAY_TOKEN не задан в настройках. "
            "Добавьте его в .env и перезапустите сервер."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_order_id(viewing_id: int) -> str:
    """
    Уникальный order_id для платёжного сервиса.
    Формат: viewing-{viewing_id}-{short_uuid}
    UUID нужен на случай повторной попытки оплаты по тому же просмотру.
    """
    return f"viewing-{viewing_id}-{uuid.uuid4().hex[:8]}"


def create_invoice(
    *,
    viewing_id: int,
    amount_kopecks: int,
    description: str,
    client_email: str | None = None,
    client_phone: str | None = None,
) -> dict[str, Any]:
    """
    Создать счёт на оплату (POST /invoices).

    Параметры
    ----------
    viewing_id     : PK записи PropertyViewing — используется в order_id.
    amount_kopecks : Сумма в копейках. Тестовый токен: не более 100 (=1 ₽).
    description    : Короткое описание для кассового чека.
    client_email   : Email покупателя (хотя бы одно из email/phone обязательно).
    client_phone   : Телефон покупателя.

    Возвращает
    ----------
    Словарь с полями invoice_id, status и прочим из ответа SmartPay.

    Исключения
    ----------
    SmartPayError — при любой проблеме: нет токена, HTTP-ошибка, плохой ответ.
    """
    service_id = getattr(settings, "SMARTPAY_SERVICE_ID", "")
    if not service_id:
        raise SmartPayError(
            "SMARTPAY_SERVICE_ID не задан в настройках."
        )

    order_id = _build_order_id(viewing_id)

    # Блок покупателя — хотя бы email или phone обязателен.
    purchaser: dict[str, Any] = {}
    if client_email:
        purchaser["email"] = client_email
    if client_phone:
        purchaser["phone"] = client_phone
    if not purchaser:
        # Если ни email, ни телефон не переданы — ставим заглушку.
        # SmartPay требует хотя бы одно поле; используем email-фиктив.
        purchaser["email"] = "noreply@agency.local"

    payload: dict[str, Any] = {
        "invoice_params": {
            "description": description[:255],
            "invoice_type": "MULTI_STAGE",  # двухстадийный — сначала холд, потом списание
        },
        "purchaser": purchaser,
        "order": {
            "order_id": order_id,
            "order_number": str(viewing_id),
            "order_date": _current_iso_date(),
            "service_id": service_id,
            "amount": amount_kopecks,
            "currency": "RUB",
            "purpose": description[:255],
            "tax_system": 1,  # УСН, доходы — самый распространённый для МСП
            "order_bundle": [
                {
                    "position_id": "1",
                    "name": description[:100],
                    "item_params": {
                        "item_code": f"viewing-{viewing_id}",
                    },
                    "quantity": {
                        "value": 1,
                        "measure": "шт",
                    },
                    "item_amount": amount_kopecks,
                    "item_currency": "RUB",
                    "item_price": amount_kopecks,
                    "discount_type": "percent",
                    "discount_value": "0",
                    "tax_type": 6,  # НДС не облагается
                    "tax_sum": 0,
                }
            ],
        },
    }

    timeout = getattr(settings, "SMARTPAY_TIMEOUT", 15)
    url = f"{SMARTPAY_BASE_URL}/invoices"

    try:
        response = requests.post(
            url,
            json=payload,
            headers=_get_headers(),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.error("SmartPay create_invoice network error: %s", exc)
        raise SmartPayError(f"Сетевая ошибка при создании счёта: {exc}") from exc

    if not response.ok:
        logger.error(
            "SmartPay create_invoice HTTP %s: %s",
            response.status_code, response.text[:500],
        )
        raise SmartPayError(
            f"SmartPay вернул ошибку {response.status_code}: "
            f"{response.text[:200]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("SmartPay create_invoice invalid JSON: %s", response.text[:500])
        raise SmartPayError("SmartPay вернул не-JSON ответ") from exc

    logger.info(
        "SmartPay invoice created: viewing_id=%s order_id=%s invoice_id=%s",
        viewing_id, order_id, data.get("invoice_id"),
    )
    return data


def get_invoice_status(invoice_id: str) -> dict[str, Any]:
    """
    Получить статус счёта (GET /invoices/{invoice_id}).

    Возвращает словарь из ответа SmartPay.
    Поле status может принимать значения:
        CREATED, PAID, CANCELLED, REFUNDED, EXPIRED.

    Исключения
    ----------
    SmartPayError — при сетевой или HTTP-ошибке.
    """
    timeout = getattr(settings, "SMARTPAY_TIMEOUT", 15)
    url = f"{SMARTPAY_BASE_URL}/invoices/{invoice_id}"

    try:
        response = requests.get(
            url,
            headers=_get_headers(),
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.error("SmartPay get_invoice_status network error: %s", exc)
        raise SmartPayError(f"Сетевая ошибка при проверке статуса: {exc}") from exc

    if not response.ok:
        logger.error(
            "SmartPay get_invoice_status HTTP %s: %s",
            response.status_code, response.text[:500],
        )
        raise SmartPayError(
            f"SmartPay вернул ошибку {response.status_code}: "
            f"{response.text[:200]}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise SmartPayError("SmartPay вернул не-JSON ответ") from exc


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _current_iso_date() -> str:
    """Дата в формате YYYY-MM-DD (требование SmartPay для поля order_date)."""
    from datetime import date
    return date.today().isoformat()
