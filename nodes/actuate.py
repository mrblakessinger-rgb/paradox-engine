"""
Actuate node — map kernel stability → actions you apply outside the kernel.

Buyer surface: "shield / quarantine / revive / open traffic / storm_mode."
Recovery-aware (v1.1): re-open concurrency when calm returns so success
can climb after hell — without abandoning cool-under-thrash.

Storm shell (v1.2): optional storm_mode deepens felt-load cut under extreme
env_load / thrash (R&D from experiments/storm_shell). DNA stays frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StormMode = Literal["off", "auto", "on"]


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
    # --- storm shell (optional) ---
    storm_active: bool = False  # True when storm shell engaged this step
    storm_scale: float = 1.0  # extra multiplier applied on top of base shield (≤1)
    # effective felt multiplier = shield_scale * storm_scale

    def as_dict(self) -> dict:
        return {
            "shield_scale": self.shield_scale,
            "quarantine_k": self.quarantine_k,
            "revive_k": self.revive_k,
            "cool_retries": self.cool_retries,
            "open_traffic": self.open_traffic,
            "concurrency_delta": self.concurrency_delta,
            "note": self.note,
            "storm_active": self.storm_active,
            "storm_scale": self.storm_scale,
            "felt_scale": self.felt_scale(),
        }

    def felt_scale(self) -> float:
        """Combined multiplier for env load (base shield × storm shell)."""
        return float(max(0.05, min(1.0, self.shield_scale * self.storm_scale)))


def _storm_shell_scale(
    *,
    env_load: float | None,
    thrash: float | None,
    stability: float,
    target: float,
    storm_mode: StormMode,
    d_env: float | None = None,
) -> tuple[bool, float]:
    """
    Storm surge shell (tightened, buyer-safe).
    Returns (active, storm_scale) where felt *= storm_scale (≤1).

    - off: never
    - on: always compute shell from env (still limp if dead)
    - auto: engage when env/thrash high or rising hard
    """
    if storm_mode == "off":
        return False, 1.0

    env = 0.0 if env_load is None else float(env_load)
    thr = 0.0 if thrash is None else float(max(0.0, thrash))
    stab = float(stability)
    d_env = 0.0 if d_env is None else float(d_env)

    # arm thresholds (env units ~ same as proof env I, often 0.5..3+, storm demos higher)
    I_arm = 1.55
    I_full = 3.4
    max_cut = 0.48

    want = storm_mode == "on"
    if storm_mode == "auto":
        want = (
            env >= I_arm
            or thr >= 0.85
            or (d_env >= 0.12 and env >= 1.2)
            or (env >= 1.35 and thr >= 0.45)
        )
    if not want and env < I_arm and thr < 0.85:
        return False, 1.0

    # depth along env
    depth = float(max(0.0, min(1.0, (env - I_arm) / max(I_full - I_arm, 1e-6))))
    depth = depth * depth * (3.0 - 2.0 * depth)
    # thrash adds depth even if env mid
    depth = min(1.0, depth + 0.25 * min(1.0, thr / 1.5))

    hold = float(max(0.0, min(1.0, (stab - 0.35) / 0.55)))
    pred = 0.0
    if d_env >= 0.12:
        pred += 0.12 * min(1.0, d_env / 0.4)
    if stab < target - 0.06:
        pred += 0.08

    cut = max_cut * depth * (0.30 + 0.70 * hold) * (1.0 + pred)
    cut = float(max(0.0, min(max_cut, cut)))

    # limp: don't fake immortality if fleet already smashed
    if stab < 0.42:
        cut *= 0.45

    scale = 1.0 - cut

    # recovery handoff: calm env + healthy → open shell
    if env < 1.85 and thr < 0.35 and stab >= target - 0.06:
        scale = min(1.0, scale + 0.12)

    scale = float(max(1.0 - max_cut, min(1.0, scale)))
    active = scale < 0.985
    return active, scale


def plan_actions(
    stability: float,
    *,
    success_rate: float | None = None,
    target: float = 0.92,
    goodput: float | None = None,
    env_load: float | None = None,
    thrash: float | None = None,
    storm_mode: StormMode = "off",
    d_env: float | None = None,
    budget_remaining: float | None = None,
) -> ActionPlan:
    """
    Policy used by portfolio + real-world demos.

    - Thrash / low success → cool + optional quarantine
    - Near target + calm env → restore + open_traffic (recovery aggressiveness)
    - Mid success with healthy kernel → nudge open, don't keep choking
    - storm_mode auto/on → deepen felt-load cut under extreme env/thrash
    - budget_remaining 0..1 → refuse open_traffic when empty (budget gate)
    """
    stab = float(stability)
    sr = float(success_rate) if success_rate is not None else None
    gp = float(goodput) if goodput is not None else None
    env = float(env_load) if env_load is not None else None
    thr = float(thrash) if thrash is not None else None
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
    if thr is not None and thr >= 1.2:
        soft_hurt = True
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

    # --- recovery / restore ---
    calm_env = env is None or env < 1.55
    very_calm = env is not None and env < 1.25
    if thr is not None and thr >= 0.6:
        calm_env = False
        very_calm = False
    kernel_ok = stab >= target - 0.04
    kernel_strong = stab >= target - 0.02

    if kernel_strong:
        revive_k = 2
        if calm_env and (sr is None or sr >= 0.30):
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

    if kernel_ok and sr is not None and 0.40 <= sr < 0.65 and calm_env and not deep_hurt:
        open_traffic = True
        cool = False
        conc_delta = max(conc_delta, 1)
        if note in ("hold", "nudge", "cool"):
            note = "climb"

    # --- budget gate (wisdom: reopen only when budget funds attempts) ---
    if budget_remaining is not None:
        br = float(max(0.0, min(1.0, budget_remaining)))
        if br < 0.08:
            open_traffic = False
            cool = True
            conc_delta = min(conc_delta, -1)
            if note in ("restore_open", "nudge_open", "climb"):
                note = "budget_gate"
        elif br < 0.20 and open_traffic:
            conc_delta = min(conc_delta, 0)

    # --- storm shell ---
    storm_active, storm_scale = _storm_shell_scale(
        env_load=env,
        thrash=thr,
        stability=stab,
        target=target,
        storm_mode=storm_mode,
        d_env=d_env,
    )
    if storm_active:
        # Shell is primarily a felt-load cut (apply_shield). Side effects stay light:
        # cool thrash, don't stampede open — but still allow revive so fleets recover.
        cool = True
        if open_traffic and (env is not None and env >= 2.2):
            open_traffic = False
            if conc_delta > 0:
                conc_delta = 0
        if conc_delta > 1:
            conc_delta = 1
        if note in ("hold", "nudge", "restore", "climb", "nudge_open", "restore_open"):
            note = "storm_shell"
        elif "+storm" not in note:
            note = f"{note}+storm"

    return ActionPlan(
        shield_scale=float(shield),
        quarantine_k=int(quarantine_k),
        revive_k=int(revive_k),
        cool_retries=bool(cool),
        open_traffic=bool(open_traffic),
        concurrency_delta=int(conc_delta),
        note=note,
        storm_active=bool(storm_active),
        storm_scale=float(storm_scale),
    )


def apply_shield(env_load: float, plan: ActionPlan) -> float:
    """Felt load after base shield × storm shell (naive world sim)."""
    return float(max(0.0, env_load * plan.felt_scale()))
