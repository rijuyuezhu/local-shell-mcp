"""Compatibility facade for shared process-service composition."""

from ..composition.services import RuntimeServices, configure_runtime_services

__all__ = ["RuntimeServices", "configure_runtime_services"]
