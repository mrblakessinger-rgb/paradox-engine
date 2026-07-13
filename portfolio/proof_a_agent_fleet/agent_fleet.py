"""
Simulated multi-agent tool fleet (the "real world" toy problem).

Each agent tries to call a fake API/tool each step.
Tools fail randomly — worse during storms and jumps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ToolAgent:
    id: int
    alive: bool = True
    success_streak: int = 0
    fail_streak: int = 0
    total_ok: int = 0
    total_try: int = 0
    quarantined: bool = False

    @property
    def success_rate(self) -> float:
        if self.total_try == 0:
            return 0.5
        return self.total_ok / self.total_try


@dataclass
class FleetWorld:
    """
    Open-source-shaped problem: a fleet of agents calling flaky tools.
    interference_level (0–3+) raises base failure probability.
    """

    n_agents: int = 20
    base_fail: float = 0.08
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0))

    def __post_init__(self):
        self.agents = [ToolAgent(id=i) for i in range(self.n_agents)]
        self.step_i = 0
        self.history: list[dict] = []
        self.recent_results: list[int] = []  # 1=ok 0=fail rolling window

    def active_agents(self) -> list[ToolAgent]:
        return [a for a in self.agents if a.alive and not a.quarantined]

    def rolling_success(self, window: int = 40) -> float:
        if not self.recent_results:
            return 0.7
        w = self.recent_results[-window:]
        return float(np.mean(w))

    def metrics(self) -> dict:
        active = self.active_agents()
        if not active:
            return {
                "success_rate": self.rolling_success(),
                "n_active": 0,
                "n_quarantined": sum(1 for a in self.agents if a.quarantined),
                "mean_agent_sr": 0.0,
                "floor_sr": 0.0,
            }
        srs = [a.success_rate for a in active]
        return {
            "success_rate": self.rolling_success(),
            "n_active": len(active),
            "n_quarantined": sum(1 for a in self.agents if a.quarantined),
            "mean_agent_sr": float(np.mean(srs)),
            "floor_sr": float(np.mean(sorted(srs)[: max(1, len(srs) // 5)])),
        }

    def step(self, interference: float) -> dict:
        """One world step: every active agent attempts one tool call."""
        p_fail = float(
            np.clip(self.base_fail + 0.18 * interference + 0.04 * (interference**1.2), 0.05, 0.92)
        )
        if self.history:
            last = self.history[-1]["step_success"]
            if last < 0.5:
                p_fail = min(0.95, p_fail + 0.08)

        ok_count = 0
        try_count = 0
        for a in self.active_agents():
            a.total_try += 1
            try_count += 1
            if self.rng.random() < p_fail:
                a.fail_streak += 1
                a.success_streak = 0
                self.recent_results.append(0)
                if a.fail_streak >= 8 and self.rng.random() < 0.2:
                    a.alive = False
            else:
                a.total_ok += 1
                ok_count += 1
                a.success_streak += 1
                a.fail_streak = 0
                self.recent_results.append(1)
        if len(self.recent_results) > 200:
            self.recent_results = self.recent_results[-200:]

        m = self.metrics()
        m.update(
            {
                "step": self.step_i,
                "interference": interference,
                "p_fail": p_fail,
                "step_success": (ok_count / try_count) if try_count else 0.0,
            }
        )
        self.history.append(m)
        self.step_i += 1
        return m

    # ----- actions from Infinity Engine actuate node -----
    def quarantine_worst(self, k: int = 1):
        active = self.active_agents()
        if not active:
            return
        active.sort(key=lambda a: a.success_rate)
        for a in active[:k]:
            a.quarantined = True

    def revive_some(self, k: int = 1):
        dead = [a for a in self.agents if not a.alive or a.quarantined]
        dead.sort(key=lambda a: a.id)
        for a in dead[:k]:
            a.alive = True
            a.quarantined = False
            a.fail_streak = 0

    def throttle_hint(self) -> int:
        """How many agents should run next step (concurrency)."""
        return len(self.active_agents())
