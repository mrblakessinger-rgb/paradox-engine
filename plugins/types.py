"""
Shared snapshot / control types — framework-agnostic.

Map *your* metrics into HealthSnapshot. Apply ControlHints to *your* actuators.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class HealthSnapshot:
    """
    One observation of outer-system health.
    Fill only what you have — missing fields are ignored.
    """

    # Core
    success_rate: float | None = None  # 0..1 jobs/agents OK
    failure_rate: float | None = None  # alt to success
    goodput: float | None = None  # useful throughput 0..1-ish
    env_load: float = 1.0  # external storm score ~0.4..3+
    thrash: float = 0.0  # retry / stampede intensity

    # Capacity
    queue_depth: float | None = None
    queue_capacity: float = 100.0
    queue_pressure: float | None = None  # 0..1+ if known directly
    arrival_rate: float | None = None
    concurrency: int | None = None  # current worker / agent slots
    budget_remaining: float | None = None  # 0..1 tokens/quota left

    # Quality / tail
    empty_tool_rate: float | None = None  # flaky tools
    latency_p95: float | None = None
    latency_ref: float = 1.0
    upstream_error_rate: float | None = None

    # Fleet identity (optional)
    n_agents: int | None = None
    n_active: int | None = None
    n_failed: int | None = None
    agent_scores: list[float] | None = None  # lower = worse (for quarantine)

    # Free-form
    tags: dict[str, Any] = field(default_factory=dict)

    def resolved_queue_pressure(self) -> float | None:
        if self.queue_pressure is not None:
            return float(self.queue_pressure)
        if self.queue_depth is not None:
            return float(self.queue_depth) / max(1.0, float(self.queue_capacity))
        return None

    def resolved_success(self) -> float | None:
        if self.success_rate is not None:
            return float(self.success_rate)
        if self.failure_rate is not None:
            return 1.0 - float(self.failure_rate)
        if self.n_agents and self.n_active is not None and self.n_agents > 0:
            return float(self.n_active) / float(self.n_agents)
        return None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ControlHints:
    """
    What your outer system should do this step.
    All fields are *hints* — you apply them in your own runtime.
    """

    # Kernel echo
    stability: float = 0.9
    I: float = 1.0
    storm_active: bool = False
    storm_reason: str = ""
    recovery_active: bool = False
    pre_arm: bool = False
    surge_risk: float = 0.0

    # Capacity / pace
    felt_load_scale: float = 1.0  # multiply env / admission by this (<1 = shield)
    max_concurrency: int | None = None  # suggested worker/agent cap
    concurrency_delta: int = 0
    open_traffic: bool = False
    cool_retries: bool = False
    retry_budget: float = 1.0  # 0..1 scale on retry attempts
    request_pace: float = 1.0  # 1 = full rate; <1 slow; >1 open up

    # Fleet surgery
    quarantine_k: int = 0  # drop/pause worst K workers
    revive_k: int = 0  # bring K back online
    quarantine_ids: list[Any] = field(default_factory=list)

    # Human-readable
    note: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    # --- convenience aliases (same spirit as proofs) ---
    @property
    def shield(self) -> float:
        return self.felt_load_scale

    def should_pause_new_work(self) -> bool:
        return self.storm_active or self.felt_load_scale < 0.55 or self.retry_budget < 0.35

    def should_open_up(self) -> bool:
        return self.open_traffic or self.recovery_active
