"""Domain errors carrying the stable machine-readable codes from API_CONTRACT.md section 2."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500
    message = "Something went wrong."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_payload(self, request_id: str | None = None) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": request_id,
            }
        }


class ValidationError(DomainError):
    code, http_status, message = "VALIDATION_ERROR", 400, "That request was not valid."


class Unauthenticated(DomainError):
    code, http_status, message = "UNAUTHENTICATED", 401, "Please sign in."


class NotFound(DomainError):
    """Also returned for resources owned by someone else - never FORBIDDEN (US-18)."""

    code, http_status, message = "NOT_FOUND", 404, "We could not find that."


class Conflict(DomainError):
    code, http_status, message = "CONFLICT", 409, "That conflicts with an existing record."


class CartChanged(DomainError):
    code, http_status = "CART_CHANGED", 409
    message = "Your order changed since we reviewed it, so let's go through it once more."


class NoConfirmation(DomainError):
    code, http_status = "NO_CONFIRMATION", 409
    message = "I need to read the order back to you before placing it."


class CartEmpty(DomainError):
    code, http_status, message = "CART_EMPTY", 409, "There is nothing in the order yet."


class ItemNotFound(DomainError):
    code, http_status, message = "ITEM_NOT_FOUND", 404, "That is not on the menu."


class ItemUnavailable(DomainError):
    code, http_status, message = "ITEM_UNAVAILABLE", 409, "That is not available right now."


class MixedRestaurants(DomainError):
    """Rule K1: one order, one kitchen."""

    code, http_status = "MIXED_RESTAURANTS", 409
    message = "That is from a different restaurant. One order comes from one kitchen."


class InvalidOptions(DomainError):
    code, http_status, message = "INVALID_OPTIONS", 400, "Those choices are not valid for that item."


class QuantityOutOfRange(DomainError):
    code, http_status = "QUANTITY_OUT_OF_RANGE", 400
    message = "Quantity must be between 1 and 20."


class LineNotFound(DomainError):
    code, http_status, message = "LINE_NOT_FOUND", 404, "That item is not in the order."


class OrderNotFound(DomainError):
    code, http_status, message = "ORDER_NOT_FOUND", 404, "We could not find that order."


class CancellationWindowExpired(DomainError):
    code, http_status = "CANCELLATION_WINDOW_EXPIRED", 409
    message = "That order is already being prepared, so it is too late to cancel it here."


class OrderNotCancellable(DomainError):
    code, http_status = "ORDER_NOT_CANCELLABLE", 409
    message = "That order can no longer be cancelled."


class InvalidTransition(DomainError):
    code, http_status, message = "INVALID_TRANSITION", 409, "That status change is not allowed."


class RateLimited(DomainError):
    code, http_status, message = "RATE_LIMITED", 429, "Too many requests. Please wait a moment."


class StorageUnavailable(DomainError):
    code, http_status = "STORAGE_UNAVAILABLE", 503
    message = "We cannot reach our systems right now."


class LLMUnavailable(DomainError):
    code, http_status = "LLM_UNAVAILABLE", 503
    message = "I cannot reach the kitchen's brain right now. Please try again."
