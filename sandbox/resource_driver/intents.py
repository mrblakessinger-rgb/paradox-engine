"""
Abstract resource intents — Paradox / ActionPlan speak this language.

No OS imports. Safe for Soft Pack core to reference later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceIntent:
    """
    What Paradox wants from the host layer this step.

    strength: 0..1 how hard to push (0 = none, 1 = max allowed by driver rails)
    """

    compute_throttle: float = 0.0   # cut workers / concurrency / batch
    memory_shed: float = 0.0        # drop caches / defer fat payloads
    gpu_defer: float = 0.0          # pause new GPU work
    io_cool: float = 0.0            # slow IO / network thrash
    note: str = ""
    reasons: list[str] = field(default_factory=list)

    def active(self) -> bool:
        return max(self.compute_throttle, self.memory_shed, self.gpu_defer, self.io_cool) > 0.02

    def as_dict(self) -> dict[str, Any]:
        return {
            "compute_throttle": self.compute_throttle,
            "memory_shed": self.memory_shed,
            "gpu_defer": self.gpu_defer,
            "io_cool": self.io_cool,
            "note": self.note,
            "reasons": list(self.reasons),
            "active": self.active(),
        }


def intents_from_plan(plan: Any, *, host: Any | None = None) -> ResourceIntent:
    """
    Map actuate ActionPlan (+ optional HostSnapshot) → ResourceIntent.

    Policy is deliberately simple: storm / pre-arm / thrash-like notes → throttle.
    Host pressure (if provided) can deepen shed/defer.
    """
    intent = ResourceIntent()
    reasons: list[str] = []

    storm = bool(getattr(plan, "storm_active", False))
    pre_arm = bool(getattr(plan, "pre_arm", False))
    cool = bool(getattr(plan, "cool_retries", False))
    open_t = bool(getattr(plan, "open_traffic", False))
    conc = int(getattr(plan, "concurrency_delta", 0) or 0)
    risk = float(getattr(plan, "surge_risk", 0.0) or 0.0)
    recovery = bool(getattr(plan, "recovery_active", False))
    note = str(getattr(plan, "note", "") or "")

    if storm or pre_arm:
        intent.compute_throttle = max(intent.compute_throttle, 0.35 + 0.25 * min(1.0, risk))
        intent.io_cool = max(intent.io_cool, 0.25)
        reasons.append("storm_or_pre_arm")
    if cool and not open_t:
        intent.compute_throttle = max(intent.compute_throttle, 0.20)
        reasons.append("cool_closed")
    if conc < 0:
        intent.compute_throttle = max(intent.compute_throttle, min(0.6, 0.15 * abs(conc)))
        reasons.append("concurrency_down")
    if risk >= 0.48:
        intent.compute_throttle = max(intent.compute_throttle, 0.30)
        intent.gpu_defer = max(intent.gpu_defer, 0.25)
        reasons.append("surge_risk")
    if recovery:
        # Climb: do not throttle hard; allow mild memory shed only if host tight
        intent.compute_throttle = min(intent.compute_throttle, 0.15)
        reasons.append("recovery_pace")
    if "horizon" in note:
        intent.compute_throttle = max(intent.compute_throttle, 0.25)
        reasons.append("horizon")

    # Optional host deepening
    if host is not None:
        cpu = float(getattr(host, "cpu_util", 0.0) or 0.0)
        mem = float(getattr(host, "mem_pressure", 0.0) or 0.0)
        gpu = float(getattr(host, "gpu_util", 0.0) or 0.0)
        if mem >= 0.75:
            intent.memory_shed = max(intent.memory_shed, min(1.0, 0.4 + 0.5 * (mem - 0.75) / 0.25))
            reasons.append("host_mem")
        if cpu >= 0.85:
            intent.compute_throttle = max(intent.compute_throttle, min(1.0, 0.35 + 0.4 * (cpu - 0.85) / 0.15))
            reasons.append("host_cpu")
        if gpu >= 0.80:
            intent.gpu_defer = max(intent.gpu_defer, min(1.0, 0.4 + 0.5 * (gpu - 0.80) / 0.20))
            reasons.append("host_gpu")

    intent.reasons = reasons
    intent.note = "+".join(reasons) if reasons else "idle"
    # clip
    for k in ("compute_throttle", "memory_shed", "gpu_defer", "io_cool"):
        setattr(intent, k, float(max(0.0, min(1.0, getattr(intent, k)))))
    return intent
