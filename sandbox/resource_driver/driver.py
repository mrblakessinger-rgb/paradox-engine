"""
ResourceDriver — maps ResourceIntent → host actions (dry-run by default).

Safety rails:
  - dry_run=True: log only, never mutate
  - max_* caps: hard ceilings on throttle/shed
  - allowlist of actions when live mode is eventually enabled
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .intents import ResourceIntent, intents_from_plan
from .sensors import HostSnapshot, SimSensors


@dataclass
class DriverConfig:
    dry_run: bool = True
    max_compute_throttle: float = 0.85
    max_memory_shed: float = 0.80
    max_gpu_defer: float = 0.90
    max_io_cool: float = 0.75
    # Future: process allowlist, cgroup path, etc.
    live_enabled: bool = False


@dataclass
class DriverAction:
    name: str
    strength: float
    detail: str
    applied: bool = False  # False in dry-run


@dataclass
class DriverResult:
    intent: ResourceIntent
    host: HostSnapshot
    actions: list[DriverAction] = field(default_factory=list)
    dry_run: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.as_dict(),
            "host": self.host.as_dict(),
            "actions": [
                {
                    "name": a.name,
                    "strength": a.strength,
                    "detail": a.detail,
                    "applied": a.applied,
                }
                for a in self.actions
            ],
            "dry_run": self.dry_run,
        }


class ResourceDriver:
    """
    Outer sandbox controller. Wire after HealthEngine.step:

        plan = out["plan"]
        result = driver.step(plan)
        # result.actions for logging / metrics; host never touched if dry_run
    """

    def __init__(
        self,
        config: DriverConfig | None = None,
        sensors: Any | None = None,
        on_action: Callable[[DriverAction], None] | None = None,
    ):
        self.config = config or DriverConfig()
        self.sensors = sensors if sensors is not None else SimSensors()
        self.on_action = on_action
        self.log: list[dict[str, Any]] = []

    def read_host(self) -> HostSnapshot:
        if hasattr(self.sensors, "read"):
            return self.sensors.read()
        return HostSnapshot()

    def step(self, plan: Any, host: HostSnapshot | None = None) -> DriverResult:
        snap = host if host is not None else self.read_host()
        intent = intents_from_plan(plan, host=snap)
        # apply rails
        intent.compute_throttle = min(intent.compute_throttle, self.config.max_compute_throttle)
        intent.memory_shed = min(intent.memory_shed, self.config.max_memory_shed)
        intent.gpu_defer = min(intent.gpu_defer, self.config.max_gpu_defer)
        intent.io_cool = min(intent.io_cool, self.config.max_io_cool)

        actions: list[DriverAction] = []
        if intent.compute_throttle > 0.02:
            actions.append(
                DriverAction(
                    "compute_throttle",
                    intent.compute_throttle,
                    f"reduce workers/batch by ~{100*intent.compute_throttle:.0f}%",
                )
            )
        if intent.memory_shed > 0.02:
            actions.append(
                DriverAction(
                    "memory_shed",
                    intent.memory_shed,
                    f"shed/defer heavy memory work strength={intent.memory_shed:.2f}",
                )
            )
        if intent.gpu_defer > 0.02:
            actions.append(
                DriverAction(
                    "gpu_defer",
                    intent.gpu_defer,
                    f"defer new GPU jobs strength={intent.gpu_defer:.2f}",
                )
            )
        if intent.io_cool > 0.02:
            actions.append(
                DriverAction(
                    "io_cool",
                    intent.io_cool,
                    f"cool IO/network thrash strength={intent.io_cool:.2f}",
                )
            )

        live = self.config.live_enabled and not self.config.dry_run
        for a in actions:
            if live:
                # Placeholder: real cgroup/CUDA hooks go here later
                a.applied = False
                a.detail += " [LIVE_NOT_IMPLEMENTED]"
            else:
                a.applied = False  # dry-run
            if self.on_action:
                self.on_action(a)

        result = DriverResult(intent=intent, host=snap, actions=actions, dry_run=not live)
        self.log.append(result.as_dict())
        if len(self.log) > 500:
            self.log = self.log[-500:]
        return result
