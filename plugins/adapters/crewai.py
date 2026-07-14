"""
CrewAI adapter — optional dependency.

    from plugins.adapters.crewai import EyeStormCrewGuard

    guard = EyeStormCrewGuard()
    # after each crew kickoff / task batch:
    ctrl = guard.after_tasks(ok=8, fail=3, env_load=1.7)
    if ctrl.should_pause_new_work():
        ...  # don't schedule next wave

No CrewAI import required for basic use — pure metrics in / controls out.
If crewai is installed, `wrap_crew_kickoff` monkey-patches a kickoff for metering.
"""

from __future__ import annotations

from typing import Any, Callable

from ..core import Eye, EyeOfTheStorm
from ..types import ControlHints, HealthSnapshot


class EyeStormCrewGuard:
    def __init__(self, eye: EyeOfTheStorm | None = None, *, seed: int = 42):
        self.eye = eye or Eye(seed=seed, world="fleet")
        self.last: ControlHints | None = None
        self._ok = 0
        self._fail = 0

    def record_task(self, *, success: bool) -> None:
        if success:
            self._ok += 1
        else:
            self._fail += 1

    def after_tasks(
        self,
        *,
        ok: int | None = None,
        fail: int | None = None,
        env_load: float = 1.0,
        thrash: float = 0.0,
        empty_tool_rate: float = 0.0,
    ) -> ControlHints:
        o = self._ok if ok is None else ok
        f = self._fail if fail is None else fail
        tot = max(1, o + f)
        snap = HealthSnapshot(
            success_rate=o / tot,
            env_load=env_load,
            thrash=thrash if thrash > 0 else min(1.5, f / tot),
            empty_tool_rate=empty_tool_rate,
            n_agents=tot,
            n_active=o,
        )
        self.last = self.eye.step(snap)
        self._ok = self._fail = 0
        return self.last

    def allow_next_wave(self, ctrl: ControlHints | None = None) -> bool:
        c = ctrl or self.last
        if c is None:
            return True
        return not c.should_pause_new_work()


def wrap_crew_kickoff(crew: Any, guard: EyeStormCrewGuard) -> Callable[..., Any]:
    """
    Optional: wrap crew.kickoff so outcomes feed the guard.
    Expects crew.kickoff to return something truthy on success.
    """
    original = crew.kickoff

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            result = original(*args, **kwargs)
            guard.record_task(success=True)
            return result
        except Exception:
            guard.record_task(success=False)
            raise

    crew.kickoff = _wrapped  # type: ignore[method-assign]
    return _wrapped
