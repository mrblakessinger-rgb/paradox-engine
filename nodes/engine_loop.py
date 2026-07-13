"""
HealthEngine — thin public loop around KERNEL_v1.

Ingest → Paradox live damper → step → storm/beacons actuate.
Paradox owns damper dial + auto storm arsenal (shell, beacons).
Once per week: scheduled arsenal drill (reason to engage storm pack).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K  # noqa: E402

from .actuate import (  # noqa: E402
    ActionPlan,
    StormLatch,
    StormMode,
    WeeklyStormDrill,
    apply_beacons_to_swarm,
    apply_paradox_damper_to_swarm,
    plan_actions,
)
from .ingest import to_interference  # noqa: E402


class HealthEngine:
    """
    Frozen-DNA health controller.

    - storm_mode auto by default (shell + beacons)
    - Paradox live damper policy each step
    - weekly arsenal drill: once per week engages storm pack on purpose
    """

    def __init__(
        self,
        seed: int = 42,
        storm_mode: StormMode = "auto",
        *,
        weekly_drill: bool = True,
        steps_per_week: int = 168,
    ):
        self.rng = np.random.default_rng(seed)
        self.agents = K.make_swarm(self.rng)
        self.paradox = K.Paradox(K.PROMOTED_DNA)
        if not isinstance(self.paradox.wisdom, dict):
            self.paradox.wisdom = {}
        self.paradox.wisdom.setdefault(
            "storm_arsenal",
            "auto storm pack engages on env/thrash/budget/goodput/I spikes; "
            "no operator switch — release when calm holds",
        )
        self.paradox.wisdom.setdefault(
            "beacon_arsenal",
            "when storm pack is active, beacons pull edge agents toward core; "
            "same latch as shell — Paradox deploys both without operator step-in",
        )
        self.paradox.wisdom.setdefault(
            "bright_path",
            "success/climb scars build competence optimism; trauma does not monopolize intuition",
        )
        self.paradox.wisdom.setdefault(
            "damper_policy",
            "Paradox owns live damper dial: up under storm/drill, ease in calm (band 1.45–2.28)",
        )
        self.paradox.wisdom.setdefault(
            "weekly_drill",
            "once per week Paradox engages storm pack for arsenal practice (weekly_arsenal_drill)",
        )
        self.paradox.install_drivers(self.agents)
        self.ambient = 0.0
        self.last_stability = 0.88
        self.steps = 0
        self.storm_mode: StormMode = storm_mode
        self.storm_latch = StormLatch()
        self.weekly_drill = WeeklyStormDrill(
            steps_per_week=steps_per_week,
            enabled=weekly_drill,
        )
        self._prev_env: float | None = None
        self._last_storm_active = False
        self._last_damper = float(self.paradox.intuition.get("damper_bias", 2.0))

    def step(
        self,
        I: float,
        *,
        success_rate: float | None = None,
        goodput: float | None = None,
        env_load: float | None = None,
        thrash: float | None = None,
        storm_mode: StormMode | None = None,
        budget_remaining: float | None = None,
        empty_tool_rate: float | None = None,
    ) -> dict[str, Any]:
        """One kernel cycle. Damper + storm/beacons + optional weekly drill."""
        I = float(np.clip(I, 0.4, 3.0))
        env = float(env_load) if env_load is not None else I
        thr = thrash
        mode: StormMode = storm_mode if storm_mode is not None else self.storm_mode

        drill = self.weekly_drill.active(self.steps) and mode == "auto"
        base_d = float(self.paradox.intuition.get("damper_bias", 2.0))

        # Paradox hand on damper *before* swarm acts (uses last storm state + drill)
        self._last_damper = apply_paradox_damper_to_swarm(
            self.agents,
            base_damper=base_d,
            storm_active=self._last_storm_active or drill,
            stability=self.last_stability,
            thrash=thr,
            target=K.TARGET_STABILITY,
            weekly_drill=drill,
        )

        for a in self.agents:
            a.step(I, self.ambient, self.rng)
        self.ambient = 0.03 * float(np.mean([a.flux for a in self.agents]))
        self.paradox.hive_pair_churn(self.agents, self.rng)
        self.paradox.install_drivers(self.agents)

        # Re-assert live damper after install (install would blend DNA back)
        self._last_damper = apply_paradox_damper_to_swarm(
            self.agents,
            base_damper=base_d,
            storm_active=self._last_storm_active or drill,
            stability=self.last_stability,
            thrash=thr,
            target=K.TARGET_STABILITY,
            weekly_drill=drill,
        )

        stab = K.stability(self.agents)
        self.last_stability = stab
        step_i = self.steps
        self.steps += 1

        d_env = None
        if self._prev_env is not None:
            d_env = float(env) - float(self._prev_env)
        self._prev_env = float(env)

        cm = float(self.paradox.intuition.get("countermeasure_invest", 0.98))
        plan = plan_actions(
            stab,
            success_rate=success_rate,
            goodput=goodput,
            env_load=float(env),
            thrash=thr,
            storm_mode=mode,
            d_env=d_env,
            budget_remaining=budget_remaining,
            empty_tool_rate=empty_tool_rate,
            kernel_I=I,
            countermeasure_invest=cm,
            storm_latch=self.storm_latch if mode == "auto" else None,
            force_storm=drill,
            force_storm_reason=self.weekly_drill.reason if drill else "",
        )

        # Update damper again if latch just flipped this step
        if plan.storm_active != self._last_storm_active or drill:
            self._last_damper = apply_paradox_damper_to_swarm(
                self.agents,
                base_damper=base_d,
                storm_active=plan.storm_active,
                stability=stab,
                thrash=thr,
                target=K.TARGET_STABILITY,
                weekly_drill=drill,
            )

        n_pulled = apply_beacons_to_swarm(self.agents, plan, ceiling=K.CEILING_SOFT)
        if n_pulled:
            stab = K.stability(self.agents)
            self.last_stability = stab

        self._last_storm_active = bool(plan.storm_active)

        return {
            "t": step_i,
            "I": I,
            "stability": stab,
            "plan": plan,
            "target": K.TARGET_STABILITY,
            "storm_mode": mode,
            "storm_active": plan.storm_active,
            "storm_reason": plan.storm_reason,
            "beacon_active": plan.beacon_active,
            "beacon_pulled": n_pulled,
            "countermeasure_invest": cm,
            "damper_live": self._last_damper,
            "damper_base": base_d,
            "weekly_drill": drill,
        }

    def step_from_metrics(
        self,
        *,
        success_rate: float | None = None,
        env_load: float = 1.0,
        thrash: float = 0.0,
        goodput: float | None = None,
        storm_mode: StormMode | None = None,
        budget_remaining: float | None = None,
        empty_tool_rate: float = 0.0,
        **ingest_kw: Any,
    ) -> dict[str, Any]:
        I = to_interference(
            success_rate=success_rate,
            env_load=env_load,
            thrash=thrash,
            budget_remaining=budget_remaining,
            empty_tool_rate=empty_tool_rate,
            **ingest_kw,
        )
        return self.step(
            I,
            success_rate=success_rate,
            goodput=goodput,
            env_load=env_load,
            thrash=thrash,
            storm_mode=storm_mode,
            budget_remaining=budget_remaining,
            empty_tool_rate=empty_tool_rate,
        )


def smoke_demo(steps: int = 200, seed: int = 42) -> dict:
    """Mild week + mid-week drill window; damper and storm reason tracked."""
    eng = HealthEngine(seed=seed, storm_mode="auto", weekly_drill=True, steps_per_week=168)
    storm_flags = []
    drill_flags = []
    dampers = []
    reasons = []
    for t in range(steps):
        # mostly calm so drill is visible as the engagement reason
        env, thr, gp, br = 1.25, 0.3, 0.48, 0.8
        out = eng.step_from_metrics(
            success_rate=gp,
            env_load=env,
            thrash=thr,
            goodput=gp,
            budget_remaining=br,
        )
        storm_flags.append(bool(out["storm_active"]))
        drill_flags.append(bool(out["weekly_drill"]))
        dampers.append(float(out["damper_live"]))
        reasons.append(out["storm_reason"])

    drill_on = [i for i, d in enumerate(drill_flags) if d]
    storm_on_drill = all(storm_flags[i] for i in drill_on) if drill_on else False
    damp_drill = float(np.mean([dampers[i] for i in drill_on])) if drill_on else 0.0
    damp_calm = float(
        np.mean([dampers[i] for i, d in enumerate(drill_flags) if not d and not storm_flags[i]])
    )

    return {
        "steps": steps,
        "drill_steps": len(drill_on),
        "storm_during_drill": storm_on_drill,
        "sample_drill_reason": reasons[drill_on[0]] if drill_on else None,
        "damper_during_drill": damp_drill,
        "damper_calm": damp_calm,
        "damper_raised_on_drill": damp_drill > damp_calm + 0.05,
        "wisdom_damper": eng.paradox.wisdom.get("damper_policy", "")[:70],
        "wisdom_weekly": eng.paradox.wisdom.get("weekly_drill", "")[:70],
    }


if __name__ == "__main__":
    print("HealthEngine smoke (Paradox damper + weekly drill)…")
    r = smoke_demo()
    for k, v in r.items():
        print(f"  {k}: {v}")
