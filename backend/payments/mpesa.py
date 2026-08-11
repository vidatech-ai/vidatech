# =============================================================================
# VIDATECH WIFI — M-Pesa shim
# backend/payments/mpesa.py
# Re-exports Paystack implementation under the old name.
# =============================================================================

from payments.paystack import initiate_stk_push, verify_webhook_signature

__all__ = ["initiate_stk_push", "verify_webhook_signature"]