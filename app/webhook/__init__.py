"""Multi-endpoint inbound webhooks."""

from app.webhook.store import get_webhook_store

__all__ = ["get_webhook_store"]
