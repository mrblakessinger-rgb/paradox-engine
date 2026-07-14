"""
Eye of the Storm — plug-in adapters for real systems.

    from plugins import Eye, HealthSnapshot

    eye = Eye(seed=42)
    snap = HealthSnapshot(success_rate=0.55, env_load=1.8, thrash=0.6)
    ctrl = eye.step(snap)
    # ctrl.max_concurrency, ctrl.retry_budget, ctrl.quarantine_k, ...

Adapters: fleet · queue · api · langgraph · crewai · httpx
No hard deps on those frameworks — optional imports only.
"""

from .core import Eye, EyeOfTheStorm, ControlHints
from .types import HealthSnapshot

__all__ = [
    "Eye",
    "EyeOfTheStorm",
    "ControlHints",
    "HealthSnapshot",
]

__version__ = "1.0.0"
