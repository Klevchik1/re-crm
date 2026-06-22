"""
Django REST Framework экшны для оплаты просмотра через SmartPay.

Подключаются к PropertyViewingViewSet как @action-декораторы.

Эндпоинты
----------
POST /api/viewings/{id}/initiate_payment/
    Создать счёт SmartPay для данного просмотра.
    Возвращает invoice_id и invoice_url для открытия в SmartApp.

GET  /api/viewings/{id}/payment_status/
    Проверить текущий статус счёта SmartPay.
    Возвращает статус из SmartPay (CREATED, PAID, CANCELLED, …).

Конфигурация (settings.py / .env)
----------------------------------
SMARTPAY_TOKEN      — Bearer-токен (тестовый или боевой)
SMARTPAY_SERVICE_ID — service_id из Studio SmartPay
SMARTPAY_AMOUNT     — сумма в копейках (по умолчанию 100 = 1 ₽ для теста)
SMARTPAY_TIMEOUT    — таймаут HTTP-запросов в секундах (по умолчанию 15)
"""
from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from . import models
from .smartpay_service import SmartPayError, create_invoice, get_invoice_status

logger = logging.getLogger(__name__)

# Ключ в JSONField PropertyViewing, где хранится invoice_id после инициации.
INVOICE_ID_KEY = "smartpay_invoice_id"


def _get_amount_kopecks() -> int:
    """
    Сумма платежа в копейках из настроек.
    По умолчанию 100 копеек = 1 ₽ (максимум для тестового токена).
    """
    return int(getattr(settings, "SMARTPAY_AMOUNT", 100))


def _get_description(viewing: models.PropertyViewing) -> str:
    """Короткое описание позиции в чеке."""
    try:
        addr = viewing.property.address
        address_str = str(addr) if addr else f"объект #{viewing.property_id}"
    except Exception:
        address_str = f"объект #{viewing.property_id}"
    return f"Просмотр недвижимости: {address_str}"


def _get_client_contacts(viewing: models.PropertyViewing) -> tuple[str | None, str | None]:
    """Вернуть (email, phone) клиента или (None, None) если профиля нет."""
    try:
        profile = viewing.client.client_profile
        return profile.email or None, profile.phone or None
    except Exception:
        email = getattr(viewing.client, "email", None) or None
        return email, None


class ViewingPaymentMixin:
    """
    Примесь с двумя @action-методами для оплаты просмотра.
    Подмешивается в PropertyViewingViewSet.
    """

    @action(detail=True, methods=["post"], url_path="initiate_payment")
    def initiate_payment(self, request, pk=None):
        """
        POST /api/viewings/{id}/initiate_payment/

        Создаёт счёт SmartPay и сохраняет invoice_id в meta-поле просмотра.
        Если invoice_id уже сохранён — возвращает его без повторного создания
        (идемпотентность: двойной клик не создаёт два счёта).

        Ответ 200 OK:
        {
            "invoice_id": "...",
            "status": "CREATED",
            "amount": 100,
            "description": "Просмотр недвижимости: ..."
        }
        """
        viewing: models.PropertyViewing = self.get_object()

        # Идемпотентность: уже есть invoice_id → просто вернуть.
        existing_id = _get_invoice_id(viewing)
        if existing_id:
            return Response(
                {
                    "invoice_id": existing_id,
                    "status": "ALREADY_CREATED",
                    "amount": _get_amount_kopecks(),
                    "description": _get_description(viewing),
                },
                status=status.HTTP_200_OK,
            )

        description = _get_description(viewing)
        client_email, client_phone = _get_client_contacts(viewing)

        try:
            result = create_invoice(
                viewing_id=viewing.pk,
                amount_kopecks=_get_amount_kopecks(),
                description=description,
                client_email=client_email,
                client_phone=client_phone,
            )
        except SmartPayError as exc:
            logger.warning("initiate_payment viewing=%s error: %s", viewing.pk, exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        invoice_id = result.get("invoice_id")
        if not invoice_id:
            logger.error(
                "SmartPay did not return invoice_id for viewing=%s: %s",
                viewing.pk, result,
            )
            return Response(
                {"detail": "SmartPay не вернул invoice_id. Проверьте токен и service_id."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Сохраняем invoice_id в JSONField «extra» или «notes» просмотра.
        # У нас в модели нет JSONField, поэтому сохраняем в notes как суффикс.
        _save_invoice_id(viewing, invoice_id)

        return Response(
            {
                "invoice_id": invoice_id,
                "status": result.get("invoice_status", "CREATED"),
                "amount": _get_amount_kopecks(),
                "description": description,
                "raw": result,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"], url_path="payment_status")
    def payment_status(self, request, pk=None):
        """
        GET /api/viewings/{id}/payment_status/

        Проверяет статус счёта SmartPay для данного просмотра.

        Ответ 200 OK:
        {
            "invoice_id": "...",
            "status": "PAID" | "CREATED" | "CANCELLED" | "EXPIRED" | ...
        }

        Ответ 404 если счёт ещё не создавался.
        """
        viewing: models.PropertyViewing = self.get_object()

        invoice_id = _get_invoice_id(viewing)
        if not invoice_id:
            return Response(
                {"detail": "Счёт ещё не создан. Сначала вызовите initiate_payment."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            result = get_invoice_status(invoice_id)
        except SmartPayError as exc:
            logger.warning("payment_status viewing=%s error: %s", viewing.pk, exc)
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "invoice_id": invoice_id,
                "status": result.get("invoice_status") or result.get("status", "UNKNOWN"),
                "raw": result,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Хранение invoice_id
# ---------------------------------------------------------------------------
# Модель PropertyViewing не имеет отдельного поля для invoice_id.
# Сохраняем его в поле notes как специальный суффикс, чтобы не трогать
# миграции в рамках этой задачи.
# Формат: «...исходные заметки...\n[smartpay_invoice_id:XXXXX]»

_NOTES_MARKER = "[smartpay_invoice_id:"
_NOTES_SUFFIX_TEMPLATE = "\n[smartpay_invoice_id:{invoice_id}]"


def _get_invoice_id(viewing: models.PropertyViewing) -> str | None:
    """Извлечь ранее сохранённый invoice_id из поля notes."""
    notes = viewing.notes or ""
    idx = notes.find(_NOTES_MARKER)
    if idx == -1:
        return None
    start = idx + len(_NOTES_MARKER)
    end = notes.find("]", start)
    if end == -1:
        return None
    return notes[start:end] or None


def _save_invoice_id(viewing: models.PropertyViewing, invoice_id: str) -> None:
    """Добавить invoice_id в поле notes просмотра и сохранить."""
    # Если уже есть — не дублируем.
    if _get_invoice_id(viewing):
        return
    suffix = _NOTES_SUFFIX_TEMPLATE.format(invoice_id=invoice_id)
    viewing.notes = (viewing.notes or "") + suffix
    viewing.save(update_fields=["notes"])
