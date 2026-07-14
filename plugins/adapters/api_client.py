"""
API / rate-limit thrash plug-in (Proof C world).

    api = ApiClientPlugin(base_rps=20)
    # after a window of calls:
    ctrl = api.observe(ok=40, err=12, status_429=8, latency_p95=2.4)
    sleep_s = api.pace_delay(ctrl)   # insert between requests
    max_retries = api.max_retries(3, ctrl)
"""

from __future__ import annotations

from typing import Any

from ..core import Eye, EyeOfTheStorm
from ..types import ControlHints, HealthSnapshot


class ApiClientPlugin:
    def __init__(
        self,
        *,
        base_rps: float = 10.0,
        seed: int = 42,
        eye: EyeOfTheStorm | None = None,
        budget_tokens: float | None = None,
    ):
        self.base_rps = float(base_rps)
        self.budget_tokens = budget_tokens
        self._budget_left = budget_tokens
        self.eye = eye or Eye(seed=seed, world="api", base_concurrency=max(1, int(base_rps)))
        self.last: ControlHints | None = None
        # rolling window tallies (caller can also pass explicit observe kwargs)
        self._ok = 0
        self._err = 0
        self._r429 = 0

    def record(self, *, ok: bool = False, status: int | None = None, error: bool = False) -> None:
        if ok:
            self._ok += 1
        if error or (status is not None and status >= 400):
            self._err += 1
        if status == 429:
            self._r429 += 1

    def spend_budget(self, n: float = 1.0) -> None:
        if self._budget_left is not None:
            self._budget_left = max(0.0, float(self._budget_left) - float(n))

    def observe(
        self,
        *,
        ok: int | None = None,
        err: int | None = None,
        status_429: int | None = None,
        env_load: float | None = None,
        latency_p95: float | None = None,
        latency_ref: float = 1.0,
        reset_window: bool = True,
    ) -> ControlHints:
        o = self._ok if ok is None else ok
        e = self._err if err is None else err
        r = self._r429 if status_429 is None else status_429
        tot = max(1, o + e)
        goodput = o / tot
        thrash = min(2.0, (e + 2.0 * r) / tot)
        # env proxy: 429 density
        if env_load is None:
            env_load = 0.8 + 2.2 * min(1.0, r / tot * 4.0) + 0.5 * thrash
        br = None
        if self.budget_tokens and self._budget_left is not None:
            br = float(self._budget_left) / float(self.budget_tokens)

        snap = HealthSnapshot(
            goodput=goodput,
            success_rate=goodput,
            env_load=float(env_load),
            thrash=thrash,
            budget_remaining=br,
            latency_p95=latency_p95,
            latency_ref=latency_ref,
        )
        self.last = self.eye.step(snap)
        if reset_window:
            self._ok = self._err = self._r429 = 0
        return self.last

    def pace_delay(self, ctrl: ControlHints | None = None) -> float:
        """Seconds to sleep between requests (0 = full tilt)."""
        c = ctrl or self.last
        if c is None:
            return 0.0
        rps = max(0.1, self.base_rps * float(c.request_pace))
        return float(1.0 / rps)

    def max_retries(self, base: int = 3, ctrl: ControlHints | None = None) -> int:
        c = ctrl or self.last
        if c is None:
            return base
        return int(max(0, round(base * c.retry_budget)))

    def allow_request(self, ctrl: ControlHints | None = None) -> bool:
        c = ctrl or self.last
        if c is None:
            return True
        if c.should_pause_new_work() and c.felt_load_scale < 0.4:
            return False
        return True

    def apply_summary(self, ctrl: ControlHints | None = None) -> dict[str, Any]:
        c = ctrl or self.last
        if c is None:
            return {}
        return {
            "pace_delay_s": self.pace_delay(c),
            "max_retries": self.max_retries(3, c),
            "allow": self.allow_request(c),
            "storm_active": c.storm_active,
            "request_pace": c.request_pace,
            "retry_budget": c.retry_budget,
            "felt_load_scale": c.felt_load_scale,
        }
