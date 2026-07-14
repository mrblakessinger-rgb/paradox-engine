"""Drop-in adapters for common stacks. Optional deps — import only what you use."""

from .fleet import FleetPlugin
from .queue import QueuePlugin
from .api_client import ApiClientPlugin

__all__ = ["FleetPlugin", "QueuePlugin", "ApiClientPlugin"]
