"""
Generic multi-agent fleet plug-in (Proof A world).

    fleet = FleetPlugin(n_agents=20)
    # each tick after tools run:
    ctrl = fleet.observe(successes=14, failures=6, env_load=1.9, empty_tools=2)
    fleet.apply(ctrl)  # quarantines / revives internal slots
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..core import Eye, EyeOfTheStorm
from ..types import ControlHints, HealthSnapshot


@dataclass
class AgentSlot:
    id: Any
    active: bool = True
    score: float = 1.0  # higher = healthier
    fails: int = 0
    ok: int = 0


class FleetPlugin:
    """
    Tracks agent slots and maps fleet health → Eye → quarantine/revive.
    Works with any framework: just report OK/fail per agent id.
    """

    def __init__(
        self,
        n_agents: int = 20,
        *,
        agent_ids: list[Any] | None = None,
        seed: int = 42,
        eye: EyeOfTheStorm | None = None,
        on_quarantine: Callable[[Any], None] | None = None,
        on_revive: Callable[[Any], None] | None = None,
    ):
        ids = agent_ids if agent_ids is not None else list(range(n_agents))
        self.agents: dict[Any, AgentSlot] = {i: AgentSlot(id=i) for i in ids}
        self.eye = eye or Eye(seed=seed, world="fleet", base_concurrency=len(ids))
        self.on_quarantine = on_quarantine
        self.on_revive = on_revive
        self.last: ControlHints | None = None

    def report(self, agent_id: Any, *, ok: bool, weight: float = 1.0) -> None:
        a = self.agents.get(agent_id)
        if a is None:
            self.agents[agent_id] = AgentSlot(id=agent_id)
            a = self.agents[agent_id]
        if ok:
            a.ok += 1
            a.score = min(2.0, a.score + 0.05 * weight)
        else:
            a.fails += 1
            a.score = max(0.0, a.score - 0.12 * weight)

    def observe(
        self,
        *,
        successes: int | None = None,
        failures: int | None = None,
        env_load: float = 1.0,
        empty_tools: int = 0,
        thrash: float = 0.0,
        total_calls: int | None = None,
    ) -> ControlHints:
        active = [a for a in self.agents.values() if a.active]
        n = max(1, len(self.agents))
        if successes is not None and failures is not None:
            tot = max(1, successes + failures)
            sr = successes / tot
        else:
            oks = sum(a.ok for a in active) or sum(a.ok for a in self.agents.values())
            fails = sum(a.fails for a in active) or sum(a.fails for a in self.agents.values())
            tot = max(1, oks + fails)
            sr = oks / tot
        empty_rate = 0.0
        if total_calls and total_calls > 0:
            empty_rate = float(empty_tools) / float(total_calls)
        elif empty_tools and (successes or failures):
            empty_rate = float(empty_tools) / max(1, (successes or 0) + (failures or 0) + empty_tools)

        scores = [a.score if a.active else -1.0 for a in self.agents.values()]
        snap = HealthSnapshot(
            success_rate=sr,
            env_load=env_load,
            thrash=thrash,
            empty_tool_rate=empty_rate,
            n_agents=n,
            n_active=len(active),
            concurrency=len(active),
            agent_scores=scores,
        )
        self.last = self.eye.step(snap)
        return self.last

    def apply(self, ctrl: ControlHints | None = None) -> dict[str, Any]:
        """Apply quarantine_k / revive_k to slots (+ optional callbacks)."""
        c = ctrl or self.last
        if c is None:
            return {"quarantined": [], "revived": []}
        ids = list(self.agents.keys())
        # map score order
        ranked_bad = sorted(ids, key=lambda i: self.agents[i].score)
        ranked_good_down = [i for i in ranked_bad if not self.agents[i].active]

        quarantined = []
        for i in ranked_bad:
            if len(quarantined) >= c.quarantine_k:
                break
            a = self.agents[i]
            if a.active:
                a.active = False
                quarantined.append(i)
                if self.on_quarantine:
                    self.on_quarantine(i)

        revived = []
        for i in ranked_good_down:
            if len(revived) >= c.revive_k:
                break
            a = self.agents[i]
            a.active = True
            a.score = max(a.score, 0.4)
            revived.append(i)
            if self.on_revive:
                self.on_revive(i)

        # also honor explicit quarantine_ids from Eye
        for i in c.quarantine_ids:
            if i in self.agents and self.agents[i].active and i not in quarantined:
                self.agents[i].active = False
                quarantined.append(i)
                if self.on_quarantine:
                    self.on_quarantine(i)

        return {
            "quarantined": quarantined,
            "revived": revived,
            "active": sum(1 for a in self.agents.values() if a.active),
            "max_concurrency": c.max_concurrency,
            "storm_active": c.storm_active,
            "felt_load_scale": c.felt_load_scale,
        }

    def active_ids(self) -> list[Any]:
        return [i for i, a in self.agents.items() if a.active]
