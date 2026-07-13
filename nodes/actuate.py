"""
Actuate node — map kernel stability → actions you apply outside the kernel.

Buyer surface: "shield / quarantine / revive / open traffic."
Recovery-aware (v1.1): re-open concurrency when calm returns so success
can climb after hell — without abandoning cool-under-thrash.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionPlan:
    """What your outer system should do this step."""

    shield_scale: float  # multiply felt env load (1.0 = no shield, 0.5 = strong)
    quarantine_k: int  # drop worst K workers/agents/clients
    revive_k: int  # bring back K previously dropped
    cool_retries: bool  # if True, damp retry/stampede multiplier
    open_traffic: bool = False  # recovery: raise concurrency / mild thrash reopen
    concurrency_delta: int = 0  # hint: +N or -N workers this step
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "shield_scale": self.shield_scale,
            "quarantine_k": self.quarantine_k,
            "revive_k": self.revive_k,
            "cool_retries": self.cool_retries,
            "open_traffic": self.open_traffic,
            "concurrency_delta": self.concurrency_delta,
            "note": self.note,
        }


def plan_actions(
    stability: float,
    *,
    success_rate: float | None = None,
    target: float = 0.92,
    goodput: float | None = None,
    env_load: float | None = None,
) -> ActionPlan:
    """
    Policy used by portfolio + real-world demos.

    - Thrash / low success → cool + optional quarantine
    - Near target + calm env → restore + open_traffic (recovery aggressiveness)
    - Mid success with healthy kernel → nudge open, don't keep choking
    """
    stab = float(stability)
    sr = float(success_rate) if success_rate is not None else None
    gp = float(goodput) if goodput is not None else None
    env = float(env_load) if env_load is not None else None
    gap = target - stab

    # Shield: healthier kernel → more load dampening
    if stab >= target - 0.01:
        shield = 0.52
    elif stab >= target - 0.05:
        shield = 0.70
    elif stab >= 0.82:
        shield = 0.86
    else:
        shield = 1.0

    quarantine_k = 0
    revive_k = 0
    cool = False
    open_traffic = False
    conc_delta = 0
    note = "hold"

    # --- protect (stricter than before: only true thrash, not mild dips) ---
    deep_hurt = (sr is not None and sr < 0.42) or (gp is not None and gp < 0.16)
    soft_hurt = gap > 0.10 or (sr is not None and sr < 0.48)
    if deep_hurt:
        quarantine_k = 1
        cool = True
        conc_delta = -2
        note = "protect"
        if sr is not None and sr < 0.38:
            shield = min(1.0, shield + 0.05)
    elif soft_hurt and (sr is None or sr < 0.52):
        cool = True
        conc_delta = -1
        note = "cool"
        if sr is not None and sr < 0.45:
            quarantine_k = 1

    # --- recovery / restore (aggressive reopen when kernel healthy + env calm) ---
    calm_env = env is None or env < 1.55
    very_calm = env is not None and env < 1.25
    kernel_ok = stab >= target - 0.04
    kernel_strong = stab >= target - 0.02

    if kernel_strong:
        revive_k = 2
        if calm_env and (sr is None or sr >= 0.30):
            # Signal open_traffic; caller must gate on budget tokens
            open_traffic = True
            cool = False
            conc_delta = max(conc_delta, 2 if very_calm else 1)
            note = "restore_open"
        else:
            cool = False if sr is not None and sr >= 0.50 else cool
            note = "restore"
    elif kernel_ok and calm_env and (sr is None or sr >= 0.38):
        revive_k = 1
        open_traffic = True
        cool = False
        conc_delta = max(conc_delta, 1)
        note = "nudge_open"
    elif stab >= 0.88:
        revive_k = 1
        note = "nudge"

    # Mid-band climb — only when not deep-hurt
    if kernel_ok and sr is not None and 0.40 <= sr < 0.65 and calm_env and not deep_hurt:
        open_traffic = True
        cool = False
        conc_delta = max(conc_delta, 1)
        if note in ("hold", "nudge", "cool"):
            note = "climb"

    return ActionPlan(
        shield_scale=float(shield),
        quarantine_k=int(quarantine_k),
        revive_k=int(revive_k),
        cool_retries=bool(cool),
        open_traffic=bool(open_traffic),
        concurrency_delta=int(conc_delta),
        note=note,
    )


def apply_shield(env_load: float, plan: ActionPlan) -> float:
    """Felt load after shield (what you pass into a naive world sim)."""
    return float(max(0.0, env_load * plan.shield_scale))
