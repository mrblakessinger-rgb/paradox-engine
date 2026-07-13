"""
Actuate node — map kernel stability → actions you apply outside the kernel.

Buyer surface: "shield / quarantine / revive / open traffic / storm pack."

Recovery-aware (v1.1): re-open concurrency when calm returns.
Storm pack (v1.3): **auto-armed by default** — Paradox-side arsenal for extreme
load. Operators do not flip a switch; trigger points engage/release the shell
with hysteresis. DNA stays frozen; wisdom names the arsenal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StormMode = Literal["off", "auto", "on"]

# =============================================================================
# Storm pack — trigger points (auto arsenal)
# Engage when extreme; release when calm. Tuned from tough-week + near-blackout.
# =============================================================================
# ENTER storm (any one true while mode=auto):
STORM_ENV_ENTER = 1.75          # env load (429 / deploy thrash band)
STORM_THRASH_ENTER = 0.75       # retry stampede
STORM_BUDGET_ENTER = 0.50       # shared quota below half + stress
STORM_GOODPUT_ENTER = 0.20      # fleet goodput floor under load
STORM_SPIKE_DENV = 0.20         # sudden env jump
STORM_SPIKE_ENV_MIN = 1.30
STORM_I_ENTER = 2.15            # kernel interference if env not wired
STORM_EMPTY_ENTER = 0.18        # empty/error tool rate under stress

# EXIT storm (all true for STORM_RELEASE_HOLD steps):
STORM_ENV_EXIT = 1.45
STORM_THRASH_EXIT = 0.40
STORM_BUDGET_EXIT = 0.65
STORM_GOODPUT_EXIT = 0.28
STORM_I_EXIT = 1.85
STORM_RELEASE_HOLD = 3          # consecutive calm steps before drop shell

# Shell physics
STORM_I_ARM = 1.55
STORM_I_FULL = 3.4
STORM_MAX_CUT = 0.48


@dataclass
class StormLatch:
    """
    Hysteresis so shell doesn't chatter on/off every step.
    HealthEngine / caller keeps one instance across steps.
    """

    active: bool = False
    calm_streak: int = 0
    last_reason: str = ""

    def update(
        self,
        *,
        want_enter: bool,
        want_exit: bool,
        reason_enter: str = "",
    ) -> bool:
        if self.active:
            if want_exit:
                self.calm_streak += 1
                if self.calm_streak >= STORM_RELEASE_HOLD:
                    self.active = False
                    self.calm_streak = 0
                    self.last_reason = "release_calm"
            else:
                self.calm_streak = 0
        else:
            if want_enter:
                self.active = True
                self.calm_streak = 0
                self.last_reason = reason_enter or "enter"
        return self.active


def evaluate_storm_triggers(
    *,
    env_load: float | None = None,
    thrash: float | None = None,
    stability: float = 0.9,
    target: float = 0.92,
    goodput: float | None = None,
    budget_remaining: float | None = None,
    empty_tool_rate: float | None = None,
    d_env: float | None = None,
    kernel_I: float | None = None,
) -> tuple[bool, bool, str]:
    """
    Returns (want_enter, want_exit, reason).

    want_enter: conditions for extreme arsenal
    want_exit: conditions safe enough to drop shell (hysteresis applied by latch)
    """
    env = 0.0 if env_load is None else float(env_load)
    thr = 0.0 if thrash is None else float(max(0.0, thrash))
    d_env = 0.0 if d_env is None else float(d_env)
    ki = None if kernel_I is None else float(kernel_I)
    gp = None if goodput is None else float(goodput)
    br = None if budget_remaining is None else float(budget_remaining)
    empty = 0.0 if empty_tool_rate is None else float(max(0.0, empty_tool_rate))

    reasons: list[str] = []
    if env >= STORM_ENV_ENTER:
        reasons.append(f"env>={STORM_ENV_ENTER}")
    if thr >= STORM_THRASH_ENTER:
        reasons.append(f"thrash>={STORM_THRASH_ENTER}")
    if br is not None and br < STORM_BUDGET_ENTER and env >= 1.35:
        reasons.append(f"budget<{STORM_BUDGET_ENTER}")
    if gp is not None and gp < STORM_GOODPUT_ENTER and env >= 1.25:
        reasons.append(f"goodput<{STORM_GOODPUT_ENTER}")
    if d_env >= STORM_SPIKE_DENV and env >= STORM_SPIKE_ENV_MIN:
        reasons.append("env_spike")
    if ki is not None and ki >= STORM_I_ENTER:
        reasons.append(f"I>={STORM_I_ENTER}")
    if empty >= STORM_EMPTY_ENTER and (env >= 1.3 or thr >= 0.5):
        reasons.append("empty_tools")
    if stability < target - 0.10 and env >= 1.4:
        reasons.append("stab_gap")

    want_enter = len(reasons) > 0

    exit_ok = (
        env < STORM_ENV_EXIT
        and thr < STORM_THRASH_EXIT
        and (br is None or br >= STORM_BUDGET_EXIT)
        and (gp is None or gp >= STORM_GOODPUT_EXIT)
        and (ki is None or ki < STORM_I_EXIT)
        and empty < STORM_EMPTY_ENTER * 0.7
        and stability >= target - 0.06
    )
    return want_enter, exit_ok, "+".join(reasons) if reasons else "none"


@dataclass
class ActionPlan:
    """What your outer system should do this step."""

    shield_scale: float
    quarantine_k: int
    revive_k: int
    cool_retries: bool
    open_traffic: bool = False
    concurrency_delta: int = 0
    note: str = ""
    storm_active: bool = False
    storm_scale: float = 1.0
    storm_reason: str = ""  # why shell engaged / held / released

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
            "storm_reason": self.storm_reason,
            "felt_scale": self.felt_scale(),
        }

    def felt_scale(self) -> float:
        return float(max(0.05, min(1.0, self.shield_scale * self.storm_scale)))


def _storm_shell_physics(
    *,
    env_load: float,
    thrash: float,
    stability: float,
    target: float,
    d_env: float,
    countermeasure: float = 0.98,
) -> float:
    """
    Depth of shell cut once arsenal is active.
    countermeasure_invest (Paradox intuition) slightly deepens max cut.
    """
    env = float(env_load)
    thr = float(max(0.0, thrash))
    cm = float(max(0.3, min(2.0, countermeasure)))
    max_cut = STORM_MAX_CUT * (0.88 + 0.14 * min(cm, 1.5))

    depth = float(max(0.0, min(1.0, (env - STORM_I_ARM) / max(STORM_I_FULL - STORM_I_ARM, 1e-6))))
    depth = depth * depth * (3.0 - 2.0 * depth)
    depth = min(1.0, depth + 0.25 * min(1.0, thr / 1.5))

    hold = float(max(0.0, min(1.0, (stability - 0.35) / 0.55)))
    pred = 0.0
    if d_env >= 0.12:
        pred += 0.12 * min(1.0, d_env / 0.4)
    if stability < target - 0.06:
        pred += 0.08

    cut = max_cut * depth * (0.30 + 0.70 * hold) * (1.0 + pred)
    cut = float(max(0.0, min(max_cut, cut)))
    if stability < 0.42:
        cut *= 0.45

    scale = 1.0 - cut
    if env < 1.85 and thr < 0.35 and stability >= target - 0.06:
        scale = min(1.0, scale + 0.12)
    return float(max(1.0 - max_cut, min(1.0, scale)))


def plan_actions(
    stability: float,
    *,
    success_rate: float | None = None,
    target: float = 0.92,
    goodput: float | None = None,
    env_load: float | None = None,
    thrash: float | None = None,
    storm_mode: StormMode = "auto",
    d_env: float | None = None,
    budget_remaining: float | None = None,
    empty_tool_rate: float | None = None,
    kernel_I: float | None = None,
    countermeasure_invest: float | None = None,
    storm_latch: StormLatch | None = None,
) -> ActionPlan:
    """
    Policy used by portfolio + real-world demos.

    storm_mode default **auto**: storm pack is in Paradox's arsenal and
    engages on trigger points without operator intervention.
    Pass storm_latch= to keep hysteresis across steps (HealthEngine does this).
    """
    stab = float(stability)
    sr = float(success_rate) if success_rate is not None else None
    gp = float(goodput) if goodput is not None else None
    env = float(env_load) if env_load is not None else None
    thr = float(thrash) if thrash is not None else None
    gap = target - stab
    cm = 0.98 if countermeasure_invest is None else float(countermeasure_invest)

    # If caller only has kernel I, treat as env proxy for triggers
    if env is None and kernel_I is not None:
        env = float(kernel_I)

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

    # --- Storm pack (arsenal) ---
    storm_active = False
    storm_scale = 1.0
    storm_reason = ""
    env_f = 0.0 if env is None else env
    thr_f = 0.0 if thr is None else thr
    d_env_f = 0.0 if d_env is None else float(d_env)

    if storm_mode == "off":
        storm_reason = "mode_off"
    else:
        want_enter, want_exit, reason = evaluate_storm_triggers(
            env_load=env,
            thrash=thr,
            stability=stab,
            target=target,
            goodput=gp,
            budget_remaining=budget_remaining,
            empty_tool_rate=empty_tool_rate,
            d_env=d_env,
            kernel_I=kernel_I,
        )
        if storm_mode == "on":
            storm_active = True
            storm_reason = "mode_on_force"
        elif storm_latch is not None:
            storm_active = storm_latch.update(
                want_enter=want_enter,
                want_exit=want_exit,
                reason_enter=reason,
            )
            storm_reason = storm_latch.last_reason
        else:
            # stateless auto (no latch): enter only; exit when want_exit
            storm_active = want_enter or (not want_exit and want_enter)
            if want_enter:
                storm_active = True
                storm_reason = reason
            else:
                storm_active = False
                storm_reason = "auto_clear" if want_exit else "auto_idle"

        if storm_active:
            storm_scale = _storm_shell_physics(
                env_load=max(env_f, thr_f * 0.5 + 1.0),
                thrash=thr_f,
                stability=stab,
                target=target,
                d_env=d_env_f,
                countermeasure=cm,
            )
            cool = True
            if open_traffic and env_f >= 2.0:
                open_traffic = False
                if conc_delta > 0:
                    conc_delta = 0
            if conc_delta > 1:
                conc_delta = 1
            if note in ("hold", "nudge", "restore", "climb", "nudge_open", "restore_open"):
                note = "storm_auto"
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
        storm_reason=storm_reason,
    )


def apply_shield(env_load: float, plan: ActionPlan) -> float:
    """Felt load after base shield × storm shell."""
    return float(max(0.0, env_load * plan.felt_scale()))
