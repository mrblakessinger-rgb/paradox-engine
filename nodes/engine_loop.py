"""
HealthEngine — thin public loop around KERNEL_v1.

Ingest → step → actuate (storm pack auto-armed).
Paradox knows the storm arsenal via countermeasure_invest + wisdom;
operators do not flip switches — trigger points engage the shell.
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
    apply_beacons_to_swarm,
    plan_actions,
)
from .ingest import to_interference  # noqa: E402


class HealthEngine:
    """
    Frozen-DNA health controller with **automatic storm pack + beacons**.

    Typical use (no storm_mode needed):
        eng = HealthEngine(seed=42)
        out = eng.step_from_metrics(success_rate=0.5, env_load=2.2, thrash=0.9)
        # out["plan"].storm_active / beacon_active when triggers fire
    """

    def __init__(self, seed: int = 42, storm_mode: StormMode = "auto"):
        self.rng = np.random.default_rng(seed)
        self.agents = K.make_swarm(self.rng)
        self.paradox = K.Paradox(K.PROMOTED_DNA)
        # Arsenal awareness (wisdom only — not a numeric DNA rewrite)
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
        self.paradox.install_drivers(self.agents)
        self.ambient = 0.0
        self.last_stability = 0.88
        self.steps = 0
        self.storm_mode: StormMode = storm_mode
        self.storm_latch = StormLatch()
        self._prev_env: float | None = None

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
        """One kernel cycle. Storm pack auto-triggers unless mode=off."""
        I = float(np.clip(I, 0.4, 3.0))
        for a in self.agents:
            a.step(I, self.ambient, self.rng)
        self.ambient = 0.03 * float(np.mean([a.flux for a in self.agents]))
        self.paradox.hive_pair_churn(self.agents, self.rng)
        self.paradox.install_drivers(self.agents)
        stab = K.stability(self.agents)
        self.last_stability = stab
        self.steps += 1

        env = env_load if env_load is not None else I
        d_env = None
        if self._prev_env is not None:
            d_env = float(env) - float(self._prev_env)
        self._prev_env = float(env)

        mode: StormMode = storm_mode if storm_mode is not None else self.storm_mode
        cm = float(self.paradox.intuition.get("countermeasure_invest", 0.98))

        plan = plan_actions(
            stab,
            success_rate=success_rate,
            goodput=goodput,
            env_load=float(env),
            thrash=thrash,
            storm_mode=mode,
            d_env=d_env,
            budget_remaining=budget_remaining,
            empty_tool_rate=empty_tool_rate,
            kernel_I=I,
            countermeasure_invest=cm,
            storm_latch=self.storm_latch if mode == "auto" else None,
        )
        # Beacons under same storm latch — kernel-side edge→core pull
        n_pulled = apply_beacons_to_swarm(self.agents, plan, ceiling=K.CEILING_SOFT)
        if n_pulled:
            stab = K.stability(self.agents)
            self.last_stability = stab
        return {
            "t": self.steps,
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
        """Ingest metrics then step (one call). Storm pack auto by default."""
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


def smoke_demo(steps: int = 50, seed: int = 42) -> dict:
    """Sanity: mild → spike → calm; expect storm auto on then off."""
    rng = np.random.default_rng(seed)
    eng = HealthEngine(seed=seed, storm_mode="auto")
    series = []
    storm_flags = []
    reasons = []
    I = 1.2
    for t in range(steps):
        if t < 10:
            env, thr, gp = 1.1, 0.2, 0.55
        elif t < 28:
            env, thr, gp = 2.3, 1.1, 0.15  # extreme — should arm
        else:
            env, thr, gp = 1.2, 0.25, 0.45  # calm — should release after hold
        out = eng.step_from_metrics(
            success_rate=gp,
            env_load=env,
            thrash=thr,
            goodput=gp,
            budget_remaining=0.4 if t < 28 else 0.85,
        )
        series.append(out["stability"])
        storm_flags.append(bool(out["storm_active"]))
        reasons.append(out["storm_reason"])
        I = out["I"]
    arr = np.array(series, float)
    armed = any(storm_flags[10:28])
    released = storm_flags[-1] is False and armed
    return {
        "steps": steps,
        "mean_stability": float(np.mean(arr)),
        "late_stability": float(np.mean(arr[-max(1, steps // 5) :])),
        "storm_armed_in_spike": armed,
        "storm_released_after_calm": released,
        "storm_frac": float(np.mean(storm_flags)),
        "sample_reasons": reasons[12:16],
        "target": K.TARGET_STABILITY,
        "wisdom_storm": eng.paradox.wisdom.get("storm_arsenal", "")[:60],
    }


if __name__ == "__main__":
    print("HealthEngine smoke (storm auto arsenal)…")
    r = smoke_demo()
    for k, v in r.items():
        print(f"  {k}: {v}")
