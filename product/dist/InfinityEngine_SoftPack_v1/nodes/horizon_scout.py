"""
Horizon scout — Paradox looks *upstream* for surge signs before peak load.

Not the credit forecast (which predicts next-step stab/goodput from *current*
sensors). This watches leading indicators and multi-step slopes to estimate
surge risk over a short horizon, so the storm pack can pre-arm.

Real-world wiring (optional but powerful):
  - queue_pressure / arrival_rate  (ingress, LB, job queue)
  - latency_p95                     (edge SLO before core fails)
  - upstream_error_rate             (dependency 5xx / timeouts)
  - empty_tool_rate trend           (tools already failing closed)
  - budget drain rate               (quota melting before thrash)

Kernel DNA stays frozen — this is Paradox-side sensing + arming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Risk bands (0..1). Tune via intuition["horizon_sensitivity"] multiplier.
RISK_WATCH = 0.32       # note / mild cool
RISK_PRE_ARM = 0.48     # pre-arm storm pack before full env enter
RISK_IMMINENT = 0.68    # treat as enter-now (strong pre-arm)


@dataclass
class HorizonReport:
    """One-step horizon assessment."""

    risk: float = 0.0                 # 0..1 surge risk over horizon
    pre_arm: bool = False             # should soft-engage arsenal early
    imminent: bool = False            # high confidence peak is near
    reasons: list[str] = field(default_factory=list)
    env_slope: float = 0.0            # multi-step Δenv / step
    thr_slope: float = 0.0
    budget_drain: float = 0.0         # positive = budget falling
    empty_slope: float = 0.0
    predicted_env: float = 0.0        # env if slope holds for horizon steps
    upstream_pressure: float = 0.0    # queue/arrival/latency composite

    def as_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "pre_arm": self.pre_arm,
            "imminent": self.imminent,
            "reasons": list(self.reasons),
            "env_slope": self.env_slope,
            "thr_slope": self.thr_slope,
            "budget_drain": self.budget_drain,
            "empty_slope": self.empty_slope,
            "predicted_env": self.predicted_env,
            "upstream_pressure": self.upstream_pressure,
        }


@dataclass
class HorizonScout:
    """
    Rolling sensor memory + surge risk score.

    Call observe() each step *before* plan_actions. Sensitivity scales thresholds
    (credit can grow horizon_sensitivity when pre-arm regret is high).
    """

    window: int = 10
    horizon_steps: int = 4
    history: list[dict[str, float]] = field(default_factory=list)
    last: HorizonReport = field(default_factory=HorizonReport)

    def reset(self) -> None:
        self.history.clear()
        self.last = HorizonReport()

    def observe(
        self,
        *,
        env_load: float,
        thrash: float = 0.0,
        budget_remaining: float | None = None,
        empty_tool_rate: float = 0.0,
        goodput: float | None = None,
        success_rate: float | None = None,
        # --- upstream / edge sensors (optional) ---
        queue_pressure: float | None = None,
        arrival_rate: float | None = None,
        latency_p95: float | None = None,
        latency_ref: float = 1.0,
        upstream_error_rate: float | None = None,
        sensitivity: float = 1.0,
    ) -> HorizonReport:
        br = 1.0 if budget_remaining is None else float(max(0.0, min(1.0, budget_remaining)))
        row = {
            "env": float(env_load),
            "thr": float(max(0.0, thrash)),
            "br": br,
            "empty": float(max(0.0, min(1.0, empty_tool_rate))),
            "gp": float(goodput) if goodput is not None else -1.0,
            "sr": float(success_rate) if success_rate is not None else -1.0,
            "queue": float(queue_pressure) if queue_pressure is not None else -1.0,
            "arrival": float(arrival_rate) if arrival_rate is not None else -1.0,
            "lat": float(latency_p95) if latency_p95 is not None else -1.0,
            "lat_ref": float(max(1e-6, latency_ref)),
            "up_err": float(upstream_error_rate) if upstream_error_rate is not None else -1.0,
        }
        self.history.append(row)
        if len(self.history) > self.window:
            self.history = self.history[-self.window :]

        rep = self._score(sensitivity=float(max(0.5, min(1.8, sensitivity))))
        self.last = rep
        return rep

    def _slope(self, key: str, n: int = 4) -> float:
        h = self.history
        if len(h) < 2:
            return 0.0
        k = min(n, len(h) - 1)
        a, b = h[-1 - k][key], h[-1][key]
        if a < 0 or b < 0:
            return 0.0
        return float((b - a) / max(1, k))

    def _score(self, *, sensitivity: float) -> HorizonReport:
        h = self.history
        if not h:
            return HorizonReport()

        cur = h[-1]
        env = cur["env"]
        thr = cur["thr"]
        br = cur["br"]
        empty = cur["empty"]

        env_slope = self._slope("env", 4)
        thr_slope = self._slope("thr", 4)
        br_slope = self._slope("br", 4)  # negative = drain
        empty_slope = self._slope("empty", 4)
        budget_drain = float(max(0.0, -br_slope))

        H = max(1, self.horizon_steps)
        predicted_env = float(env + env_slope * H)

        # Upstream composite (only if any sensor present)
        up_parts: list[float] = []
        reasons: list[str] = []
        if cur["queue"] >= 0:
            up_parts.append(min(1.0, cur["queue"]))
            if cur["queue"] >= 0.45:
                reasons.append("upstream_queue")
        if cur["arrival"] >= 0:
            # arrival > 1.0 = above nominal rate
            up_parts.append(min(1.0, max(0.0, (cur["arrival"] - 0.85) / 0.8)))
            if cur["arrival"] >= 1.15:
                reasons.append("arrival_ramp")
        if cur["lat"] >= 0:
            lat_pain = max(0.0, (cur["lat"] / cur["lat_ref"]) - 1.0)
            up_parts.append(min(1.0, lat_pain / 1.5))
            if lat_pain >= 0.35:
                reasons.append("latency_creep")
        if cur["up_err"] >= 0:
            up_parts.append(min(1.0, cur["up_err"] / 0.25))
            if cur["up_err"] >= 0.08:
                reasons.append("upstream_errors")

        upstream = float(sum(up_parts) / len(up_parts)) if up_parts else 0.0

        risk = 0.0

        # 1) Env climbing toward storm enter band (before peak)
        if env_slope > 0.06 and env >= 1.15:
            climb = min(1.0, env_slope / 0.35)
            risk += 0.28 * climb
            reasons.append("env_climbing")
        if predicted_env >= 1.75 and env < 1.75:
            risk += 0.22
            reasons.append("env_horizon_breach")
        if predicted_env >= 2.1 and env < 2.0:
            risk += 0.12
            reasons.append("env_horizon_hard")

        # 2) Thrash building while load still moderate (stampede prelude)
        if thr_slope > 0.05 and thr >= 0.25 and env < 2.0:
            risk += 0.18 * min(1.0, thr_slope / 0.25)
            reasons.append("thrash_building")

        # 3) Budget melting (quota cliff ahead)
        if budget_drain > 0.02 and br < 0.85:
            risk += 0.16 * min(1.0, budget_drain / 0.12)
            reasons.append("budget_drain")
        if br < 0.55 and env >= 1.2:
            risk += 0.10
            reasons.append("budget_low")

        # 4) Empty/error tools rising (fail-closed path heating up)
        if empty_slope > 0.015 or empty >= 0.10:
            risk += 0.12 * min(1.0, max(empty, empty_slope * 8))
            reasons.append("empty_tools_rising")

        # 5) Success/goodput soft under mild load (early degradation)
        if cur["sr"] >= 0 and cur["sr"] < 0.48 and 1.15 <= env < 1.85:
            risk += 0.10
            reasons.append("sr_soft_early")
        if cur["gp"] >= 0 and cur["gp"] < 0.24 and 1.2 <= env < 1.9:
            risk += 0.08
            reasons.append("gp_soft_early")

        # 6) Explicit upstream pressure (best early warning if wired)
        if upstream > 0.15:
            risk += 0.34 * min(1.0, upstream)
            # reasons already added per-sensor
        # Combined prelude: queue+arrival heating while core env still sub-peak
        if upstream >= 0.30 and env < 1.70 and (env_slope > 0.02 or thr_slope > 0.03):
            risk += 0.14
            reasons.append("upstream_prelude")

        # 1-step spike (kept, but weaker than multi-step climb)
        if len(h) >= 2:
            d1 = env - h[-2]["env"]
            if d1 >= 0.18 and env >= 1.25:
                risk += 0.14
                reasons.append("env_step_spike")

        risk = float(max(0.0, min(1.0, risk * sensitivity)))
        # Dedup reasons preserving order
        seen: set[str] = set()
        uniq: list[str] = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                uniq.append(r)

        pre = risk >= RISK_PRE_ARM
        imm = risk >= RISK_IMMINENT
        return HorizonReport(
            risk=risk,
            pre_arm=pre,
            imminent=imm,
            reasons=uniq,
            env_slope=env_slope,
            thr_slope=thr_slope,
            budget_drain=budget_drain,
            empty_slope=empty_slope,
            predicted_env=predicted_env,
            upstream_pressure=upstream,
        )
