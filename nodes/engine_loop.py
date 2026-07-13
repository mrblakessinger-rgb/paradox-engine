"""
HealthEngine — thin public loop around KERNEL_v1.

Ingest → step → (caller uses actuate). Kernel DNA stays inside KERNEL_v1.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

# Engine root = parent of nodes/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K  # noqa: E402

from .actuate import ActionPlan, plan_actions  # noqa: E402
from .ingest import to_interference  # noqa: E402


class HealthEngine:
    """
    Frozen-DNA health controller.

    Typical use:
        eng = HealthEngine(seed=42)
        I = to_interference(success_rate=0.6, env_load=1.5)
        out = eng.step(I)
        # out["stability"], out["plan"]
    """

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)
        self.agents = K.make_swarm(self.rng)
        self.paradox = K.Paradox(K.PROMOTED_DNA)
        self.paradox.install_drivers(self.agents)
        self.ambient = 0.0
        self.last_stability = 0.88
        self.steps = 0

    def step(
        self,
        I: float,
        *,
        success_rate: float | None = None,
        goodput: float | None = None,
    ) -> dict[str, Any]:
        """One kernel cycle at interference I. Returns stability + action plan."""
        I = float(np.clip(I, 0.4, 3.0))
        for a in self.agents:
            a.step(I, self.ambient, self.rng)
        self.ambient = 0.03 * float(np.mean([a.flux for a in self.agents]))
        self.paradox.hive_pair_churn(self.agents, self.rng)
        self.paradox.install_drivers(self.agents)
        stab = K.stability(self.agents)
        self.last_stability = stab
        self.steps += 1
        plan = plan_actions(stab, success_rate=success_rate, goodput=goodput, target=K.TARGET_STABILITY)
        return {
            "t": self.steps,
            "I": I,
            "stability": stab,
            "plan": plan,
            "target": K.TARGET_STABILITY,
        }

    def step_from_metrics(
        self,
        *,
        success_rate: float | None = None,
        env_load: float = 1.0,
        thrash: float = 0.0,
        goodput: float | None = None,
        **ingest_kw: Any,
    ) -> dict[str, Any]:
        """Ingest metrics then step (one call)."""
        I = to_interference(
            success_rate=success_rate,
            env_load=env_load,
            thrash=thrash,
            **ingest_kw,
        )
        return self.step(I, success_rate=success_rate, goodput=goodput)


def smoke_demo(steps: int = 40, seed: int = 42) -> dict:
    """Quick sanity: variable I, report late stability."""
    rng = np.random.default_rng(seed)
    eng = HealthEngine(seed=seed)
    series = []
    I = 1.5
    for _ in range(steps):
        I = float(np.clip(I + rng.normal(0, 0.08), 0.7, 2.9))
        if rng.random() < 0.1:
            I = float(rng.choice([1.0, 1.8, 2.5, 2.9]))
        out = eng.step(I, success_rate=0.55 + 0.1 * rng.normal())
        series.append(out["stability"])
    arr = np.array(series, float)
    return {
        "steps": steps,
        "mean_stability": float(np.mean(arr)),
        "late_stability": float(np.mean(arr[-max(1, steps // 5) :])),
        "min_stability": float(np.min(arr)),
        "target": K.TARGET_STABILITY,
    }


if __name__ == "__main__":
    print("HealthEngine smoke demo…")
    r = smoke_demo()
    for k, v in r.items():
        print(f"  {k}: {v}")
