"""
Generic worker-queue plug-in (Proof B world).

    q = QueuePlugin(capacity=80, base_workers=12)
    ctrl = q.tick(depth=55, success_rate=0.48, env_load=2.1, thrash=0.9)
    workers = ctrl.max_concurrency
    if ctrl.cool_retries: reduce_retry_storm()
"""

from __future__ import annotations

from typing import Any, Callable

from ..core import Eye, EyeOfTheStorm
from ..types import ControlHints, HealthSnapshot


class QueuePlugin:
    def __init__(
        self,
        *,
        capacity: float = 80.0,
        base_workers: int = 12,
        max_workers: int = 48,
        seed: int = 42,
        eye: EyeOfTheStorm | None = None,
        set_workers: Callable[[int], None] | None = None,
        set_retry_budget: Callable[[float], None] | None = None,
        pause_admissions: Callable[[], None] | None = None,
        resume_admissions: Callable[[], None] | None = None,
    ):
        self.capacity = float(capacity)
        self.set_workers = set_workers
        self.set_retry_budget = set_retry_budget
        self.pause_admissions = pause_admissions
        self.resume_admissions = resume_admissions
        self.eye = eye or Eye(
            seed=seed,
            world="queue",
            base_concurrency=base_workers,
            max_concurrency=max_workers,
            min_concurrency=1,
        )
        self.last: ControlHints | None = None

    def tick(
        self,
        *,
        depth: float,
        success_rate: float,
        env_load: float = 1.0,
        thrash: float = 0.0,
        arrival_rate: float | None = None,
        workers: int | None = None,
    ) -> ControlHints:
        snap = HealthSnapshot(
            success_rate=success_rate,
            env_load=env_load,
            thrash=thrash,
            queue_depth=float(depth),
            queue_capacity=self.capacity,
            arrival_rate=arrival_rate,
            concurrency=workers,
        )
        self.last = self.eye.step(snap)
        return self.last

    def apply(self, ctrl: ControlHints | None = None) -> dict[str, Any]:
        c = ctrl or self.last
        if c is None:
            return {}
        if self.set_workers and c.max_concurrency is not None:
            self.set_workers(int(c.max_concurrency))
        if self.set_retry_budget:
            self.set_retry_budget(float(c.retry_budget))
        if c.should_pause_new_work() and self.pause_admissions:
            self.pause_admissions()
        elif c.should_open_up() and self.resume_admissions:
            self.resume_admissions()
        return {
            "workers": c.max_concurrency,
            "retry_budget": c.retry_budget,
            "pause_new": c.should_pause_new_work(),
            "storm_active": c.storm_active,
            "queue_pressure": None,
            "felt_load_scale": c.felt_load_scale,
            "note": c.note,
        }
