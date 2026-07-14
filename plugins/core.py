"""
Eye of the Storm — one object, any system.

    eye = Eye(seed=42)
    ctrl = eye.step(HealthSnapshot(success_rate=0.5, env_load=2.0, thrash=0.8))
    apply(ctrl)  # your code
    eye.feedback(goodput=0.4, alive_frac=0.7)  # optional credit loop
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# repo root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nodes.engine_loop import HealthEngine  # noqa: E402
from nodes.ingest import from_api, from_fleet, from_queue, to_interference  # noqa: E402

from .types import ControlHints, HealthSnapshot


class EyeOfTheStorm:
    """
    Thin façade over HealthEngine for plug-in use.

    World presets bias ingest mapping (still one kernel):
      - auto   : general to_interference
      - fleet  : Proof-A shaped
      - queue  : Proof-B shaped
      - api    : Proof-C shaped
    """

    def __init__(
        self,
        seed: int = 42,
        *,
        world: str = "auto",
        storm_mode: str = "auto",
        credit_loop: bool = True,
        weekly_drill: bool = False,  # quieter default for production plug-ins
        base_concurrency: int = 16,
        max_concurrency: int = 64,
        min_concurrency: int = 1,
    ):
        self.world = (world or "auto").lower()
        self.base_concurrency = int(base_concurrency)
        self.max_concurrency = int(max_concurrency)
        self.min_concurrency = int(min_concurrency)
        self._current_conc = int(base_concurrency)
        self.engine = HealthEngine(
            seed=seed,
            storm_mode=storm_mode,  # type: ignore[arg-type]
            weekly_drill=weekly_drill,
            credit_loop=credit_loop,
        )
        self.last: ControlHints | None = None
        self.steps = 0

    # --- ingest ---
    def interference(self, snap: HealthSnapshot) -> float:
        sr = snap.resolved_success()
        qp = snap.resolved_queue_pressure()
        w = self.world

        if w == "fleet":
            return from_fleet(sr if sr is not None else 0.55, float(snap.env_load))
        if w == "queue":
            depth = float(snap.queue_depth or 0.0)
            return from_queue(
                sr if sr is not None else 0.55,
                float(snap.env_load),
                queue_depth=depth,
                capacity=float(snap.queue_capacity),
            )
        if w == "api":
            gp = float(snap.goodput) if snap.goodput is not None else (sr if sr is not None else 0.4)
            return from_api(
                gp,
                float(snap.env_load),
                retries=float(snap.thrash),
                budget_remaining=snap.budget_remaining,
            )
        # auto / general
        return to_interference(
            success_rate=sr,
            failure_rate=snap.failure_rate if sr is None else None,
            env_load=float(snap.env_load),
            thrash=float(snap.thrash),
            queue_pressure=float(qp or 0.0),
            empty_tool_rate=float(snap.empty_tool_rate or 0.0),
            budget_remaining=snap.budget_remaining,
            latency_p95=snap.latency_p95,
            latency_ref=float(snap.latency_ref),
        )

    def step(self, snap: HealthSnapshot) -> ControlHints:
        """Observe → kernel step → control hints."""
        I = self.interference(snap)
        sr = snap.resolved_success()
        qp = snap.resolved_queue_pressure()
        out = self.engine.step(
            I,
            success_rate=sr,
            goodput=snap.goodput if snap.goodput is not None else sr,
            env_load=float(snap.env_load),
            thrash=float(snap.thrash),
            budget_remaining=snap.budget_remaining,
            empty_tool_rate=snap.empty_tool_rate,
            queue_pressure=qp,
            arrival_rate=snap.arrival_rate,
            latency_p95=snap.latency_p95,
            latency_ref=float(snap.latency_ref),
            upstream_error_rate=snap.upstream_error_rate,
        )
        plan = out["plan"]
        hints = self._to_hints(out, plan, snap)
        self.last = hints
        self.steps += 1
        return hints

    def step_metrics(self, **kwargs: Any) -> ControlHints:
        """Convenience: eye.step_metrics(success_rate=0.5, env_load=2.0, thrash=0.7)."""
        return self.step(HealthSnapshot(**kwargs))

    def feedback(self, *, goodput: float, alive_frac: float, stability: float | None = None) -> dict | None:
        """Optional: close credit loop after you applied controls."""
        return self.engine.observe_actual(
            goodput=float(goodput),
            alive_frac=float(alive_frac),
            stability=stability,
        )

    def felt_env(self, env_load: float, hints: ControlHints | None = None) -> float:
        """Apply shield to an env load number (Proof-style)."""
        h = hints or self.last
        if h is None:
            return float(env_load)
        return float(max(0.0, float(env_load) * float(h.felt_load_scale)))

    # --- internal ---
    def _to_hints(self, out: dict, plan: Any, snap: HealthSnapshot) -> ControlHints:
        felt = float(plan.felt_scale())
        cool = bool(plan.cool_retries)
        # retry budget: cool → cut hard; storm → cut more
        retry = 1.0
        if cool:
            retry *= 0.45
        if plan.storm_active:
            retry *= 0.55
        if plan.recovery_active:
            retry = min(1.0, retry + 0.15)
        retry = float(max(0.1, min(1.0, retry)))

        # concurrency
        base = int(snap.concurrency if snap.concurrency is not None else self._current_conc)
        delta = int(plan.concurrency_delta)
        if plan.storm_active:
            delta = min(delta, -max(1, base // 4))
        if plan.open_traffic or plan.recovery_active:
            delta = max(delta, 1)
        # scale by felt shield
        target = int(round(base * felt)) + delta
        target = int(max(self.min_concurrency, min(self.max_concurrency, target)))
        self._current_conc = target

        # request pace mirrors felt + open
        pace = felt
        if plan.open_traffic:
            pace = min(1.15, pace + 0.1)
        if plan.storm_active:
            pace = min(pace, 0.7)

        q_ids: list[Any] = []
        k = int(plan.quarantine_k)
        if k > 0 and snap.agent_scores:
            # lowest scores first
            ranked = sorted(enumerate(snap.agent_scores), key=lambda x: x[1])
            q_ids = [i for i, _ in ranked[:k]]

        note = str(getattr(plan, "note", "") or "")
        if plan.storm_active:
            note = (note + f" | storm:{plan.storm_reason}").strip(" |")
        if plan.recovery_active:
            note = (note + " | recovery").strip(" |")

        return ControlHints(
            stability=float(out["stability"]),
            I=float(out["I"]),
            storm_active=bool(plan.storm_active),
            storm_reason=str(plan.storm_reason or ""),
            recovery_active=bool(plan.recovery_active),
            pre_arm=bool(getattr(plan, "pre_arm", False)),
            surge_risk=float(getattr(plan, "surge_risk", 0.0) or 0.0),
            felt_load_scale=felt,
            max_concurrency=target,
            concurrency_delta=delta,
            open_traffic=bool(plan.open_traffic),
            cool_retries=cool,
            retry_budget=retry,
            request_pace=float(max(0.05, min(1.25, pace))),
            quarantine_k=k,
            revive_k=int(plan.revive_k),
            quarantine_ids=q_ids,
            note=note,
            plan=plan.as_dict() if hasattr(plan, "as_dict") else {},
            raw={
                "t": out.get("t"),
                "damper_live": out.get("damper_live"),
                "horizon": out.get("horizon"),
                "world": self.world,
            },
        )


# short alias
Eye = EyeOfTheStorm
