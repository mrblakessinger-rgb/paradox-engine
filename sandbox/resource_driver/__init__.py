"""
Resource sandbox — host CPU/GPU/RAM *outside* Paradox core.

Paradox emits abstract ResourceIntent; this package maps them.
Default mode is dry-run (no OS mutations).
"""

from .intents import ResourceIntent, intents_from_plan
from .sensors import HostSnapshot, SimSensors, snapshot_from_dict
from .driver import ResourceDriver, DriverConfig

__all__ = [
    "ResourceIntent",
    "intents_from_plan",
    "HostSnapshot",
    "SimSensors",
    "snapshot_from_dict",
    "ResourceDriver",
    "DriverConfig",
]
