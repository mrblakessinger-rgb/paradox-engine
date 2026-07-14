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

# Paradox-owned live damper band (not uncapped PTSD)
DAMPER_LIVE_FLOOR = 1.45
DAMPER_LIVE_CEILING = 2.28

# Weekly arsenal drill (once per week of steps)
WEEKLY_DRILL_STEPS_PER_WEEK = 168  # 7d × 24h
WEEKLY_DRILL_OFFSET = 48           # ~Wed if Mon=0 (mid-week exercise)
WEEKLY_DRILL_DURATION = 16         # ~16 steps of forced arsenal practice
WEEKLY_DRILL_REASON = "weekly_arsenal_drill"


@dataclass
class WeeklyStormDrill:
    """
    Once a week, Paradox has a standing reason to engage the storm pack
    (shell + beacons + damper upshift) even if env is only moderately hard.
    Keeps the arsenal practiced; operators still need not intervene.
    """

    steps_per_week: int = WEEKLY_DRILL_STEPS_PER_WEEK
    offset: int = WEEKLY_DRILL_OFFSET
    duration: int = WEEKLY_DRILL_DURATION
    reason: str = WEEKLY_DRILL_REASON
    enabled: bool = True

    def active(self, step_index: int) -> bool:
        if not self.enabled or self.steps_per_week <= 0:
            return False
        pos = int(step_index) % int(self.steps_per_week)
        return self.offset <= pos < self.offset + self.duration


def paradox_damper_policy(
    base_damper: float,
    *,
    storm_active: bool,
    stability: float,
    thrash: float | None = None,
    target: float = 0.92,
    weekly_drill: bool = False,
    recovery: bool = False,
    recovery_drive: float = 1.0,
) -> float:
    """
    Paradox owns the live damper dial.
    recovery=True: drop damper faster — internal desire to climb back after surge.
    """
    d = float(base_damper)
    thr = 0.0 if thrash is None else float(max(0.0, thrash))
    gap = float(target) - float(stability)
    rd = float(max(0.5, min(2.0, recovery_drive)))

    if storm_active or weekly_drill:
        d += 0.10 + 0.08 * min(1.0, thr / 1.5)
        if gap > 0.04:
            d += 0.05
        if weekly_drill and not storm_active:
            d += 0.04
    elif recovery:
        # Desire to recover: ease viscosity quickly so revive/open can work
        d -= 0.09 * rd
        if gap > 0.02:
            d -= 0.04 * rd
        if thr < 0.55:
            d -= 0.03 * rd
        if rd >= 1.4:
            d -= 0.02  # extra eagerness at high desire
    else:
        if stability >= target - 0.03:
            d -= 0.045
        else:
            d -= 0.02
        if thr < 0.35:
            d -= 0.015

    return float(max(DAMPER_LIVE_FLOOR, min(DAMPER_LIVE_CEILING, d)))


def apply_paradox_damper_to_swarm(
    agents: list,
    *,
    base_damper: float,
    storm_active: bool,
    stability: float,
    thrash: float | None = None,
    target: float = 0.92,
    weekly_drill: bool = False,
    recovery: bool = False,
    recovery_drive: float = 1.0,
) -> float:
    """Install live damper into swarm instincts (one-way; swarm does not know source)."""
    eff = paradox_damper_policy(
        base_damper,
        storm_active=storm_active,
        stability=stability,
        thrash=thrash,
        target=target,
        weekly_drill=weekly_drill,
        recovery=recovery,
        recovery_drive=recovery_drive,
    )
    for a in agents:
        if not hasattr(a, "instinct") or a.instinct is None:
            continue
        a.instinct["damper_bias"] = float(eff)
    return eff


# Post-storm recovery desire (internal drive to climb back fast)
RECOVERY_HOLD_STEPS = 18  # steps of aggressive revive/open after storm releases
RECOVERY_DRIVE_DEFAULT = 1.15
# Env soft enough to treat as "post-surge climb" even if gp still low
RECOVERY_ENV_CLEAR = 1.20
RECOVERY_ENV_SOFT = 1.35  # residual shell + climb assist


@dataclass
class StormLatch:
    """
    Hysteresis so shell doesn't chatter on/off every step.
    Tracks post-release recovery window (desire to climb back).
    """

    active: bool = False
    calm_streak: int = 0
    last_reason: str = ""
    recovery_steps_left: int = 0  # >0 ⇒ recovery drive engaged
    hold_steps: int = RECOVERY_HOLD_STEPS  # may scale with recovery_drive

    def update(
        self,
        *,
        want_enter: bool,
        want_exit: bool,
        reason_enter: str = "",
        recovery_hold: int | None = None,
    ) -> bool:
        hold = int(recovery_hold) if recovery_hold is not None else self.hold_steps
        if self.active:
            if want_exit:
                self.calm_streak += 1
                if self.calm_streak >= STORM_RELEASE_HOLD:
                    self.active = False
                    self.calm_streak = 0
                    self.last_reason = "release_calm"
                    # Keep any pre-armed desire window; at least full hold after release
                    self.recovery_steps_left = max(
                        self.recovery_steps_left, max(RECOVERY_HOLD_STEPS, hold)
                    )
            else:
                self.calm_streak = 0
            # While shell holds, do not burn recovery timer — it is for post-release climb
        else:
            if want_enter:
                self.active = True
                self.calm_streak = 0
                self.last_reason = reason_enter or "enter"
                # Preserve armed desire across brief re-entry; don't wipe climb urge
                if self.recovery_steps_left > 0:
                    self.recovery_steps_left = max(6, min(self.recovery_steps_left, hold))
            elif self.recovery_steps_left > 0:
                self.recovery_steps_left -= 1
        return self.active

    @property
    def in_recovery(self) -> bool:
        return (not self.active) and self.recovery_steps_left > 0

    def arm_recovery(self, steps: int | None = None) -> None:
        """Desire window: call when load drops hard even if shell still releasing."""
        n = int(steps) if steps is not None else RECOVERY_HOLD_STEPS
        self.recovery_steps_left = max(self.recovery_steps_left, n)


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

    # Full calm exit (strict) — preferred when fleet already climbing
    exit_strict = (
        env < STORM_ENV_EXIT
        and thr < STORM_THRASH_EXIT
        and (br is None or br >= STORM_BUDGET_EXIT)
        and (gp is None or gp >= STORM_GOODPUT_EXIT)
        and (ki is None or ki < STORM_I_EXIT)
        and empty < STORM_EMPTY_ENTER * 0.7
        and stability >= target - 0.06
    )
    # Env-led soft exit: load clearly dropped after surge; do not wait forever
    # on goodput (chicken-egg: shell holds → gp stuck → never release → no climb).
    # Recovery desire then owns the climb. Thrash threshold soft when env is calm.
    thr_exit_cap = 1.35 if env < 1.05 else 1.05  # very calm env → tolerate residual thrash
    exit_env_clear = (
        env < RECOVERY_ENV_CLEAR
        and thr < thr_exit_cap
        and (br is None or br >= 0.48)
        and (gp is None or gp >= 0.12)
        and (ki is None or ki < STORM_I_EXIT + 0.20)
        and empty < STORM_EMPTY_ENTER * 1.05
        and stability >= target - 0.16
    )
    exit_ok = bool(exit_strict or exit_env_clear)
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
    # --- beacons (edge → core), same latch as storm ---
    beacon_active: bool = False
    beacon_n: int = 0  # number of core attractors
    beacon_edge_frac: float = 0.0  # fraction of fleet treated as edge
    beacon_pull: float = 0.0  # 0..1 pull strength toward core
    recovery_active: bool = False  # post-storm climb drive
    # --- horizon scout (upstream / leading-indicator pre-arm) ---
    pre_arm: bool = False
    surge_risk: float = 0.0
    horizon_reasons: str = ""

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
            "beacon_active": self.beacon_active,
            "beacon_n": self.beacon_n,
            "beacon_edge_frac": self.beacon_edge_frac,
            "beacon_pull": self.beacon_pull,
            "recovery_active": self.recovery_active,
            "pre_arm": self.pre_arm,
            "surge_risk": self.surge_risk,
            "horizon_reasons": self.horizon_reasons,
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
    force_storm: bool = False,
    force_storm_reason: str = "",
    recovery_drive: float | None = None,
    surge_risk: float | None = None,
    horizon_pre_arm: bool = False,
    horizon_imminent: bool = False,
    horizon_reasons: str = "",
) -> ActionPlan:
    """
    Policy used by portfolio + real-world demos.

    storm_mode default **auto**: storm pack is in Paradox's arsenal and
    engages on trigger points without operator intervention.
    Pass storm_latch= to keep hysteresis across steps (HealthEngine does this).
    force_storm: weekly arsenal drill / Paradox scheduled exercise.
    recovery_drive: internal desire to climb after surge (default 1.0).
    surge_risk / horizon_*: HorizonScout leading-indicator pre-arm (upstream look).
    """
    stab = float(stability)
    sr = float(success_rate) if success_rate is not None else None
    gp = float(goodput) if goodput is not None else None
    env = float(env_load) if env_load is not None else None
    thr = float(thrash) if thrash is not None else None
    gap = target - stab
    cm = 0.98 if countermeasure_invest is None else float(countermeasure_invest)
    rd = 1.0 if recovery_drive is None else float(max(0.5, min(2.2, recovery_drive)))
    risk = 0.0 if surge_risk is None else float(max(0.0, min(1.0, surge_risk)))
    hold_steps = int(round(RECOVERY_HOLD_STEPS * (0.85 + 0.25 * min(rd, 2.0))))
    hold_steps = max(12, min(28, hold_steps))
    if storm_latch is not None:
        storm_latch.hold_steps = hold_steps

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

    recovery_active = False

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

    # --- Storm pack + beacons (arsenal) ---
    storm_active = False
    storm_scale = 1.0
    storm_reason = ""
    beacon_active = False
    beacon_n = 0
    beacon_edge_frac = 0.0
    beacon_pull = 0.0
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
        # Horizon scout: enter *before* peak if leading indicators say surge is coming
        horizon_enter = False
        if horizon_imminent or (horizon_pre_arm and risk >= 0.48):
            # Only pre-arm when not already deep calm false-positive: need some heat
            mild_heat = env_f >= 1.10 or thr_f >= 0.30 or risk >= 0.55
            if mild_heat and not want_enter:
                want_enter = True
                horizon_enter = True
                hr = horizon_reasons or "horizon"
                reason = f"horizon_pre_arm:{hr}" if not horizon_imminent else f"horizon_imminent:{hr}"
            elif mild_heat and want_enter and horizon_pre_arm:
                # Tag existing enter with horizon (credit can learn "armed early")
                horizon_enter = True
                if "horizon" not in reason:
                    reason = f"{reason}+horizon"
        if force_storm:
            want_enter = True
            want_exit = False
            reason = force_storm_reason or WEEKLY_DRILL_REASON
        if storm_mode == "on":
            storm_active = True
            storm_reason = "mode_on_force"
        elif storm_latch is not None:
            storm_active = storm_latch.update(
                want_enter=want_enter,
                want_exit=want_exit and not force_storm,
                reason_enter=reason,
                recovery_hold=hold_steps,
            )
            storm_reason = storm_latch.last_reason
            if force_storm and storm_active:
                storm_reason = force_storm_reason or WEEKLY_DRILL_REASON
            elif storm_active and horizon_enter and "horizon" in reason:
                storm_reason = reason
        else:
            if want_enter or force_storm:
                storm_active = True
                storm_reason = reason if want_enter else (force_storm_reason or WEEKLY_DRILL_REASON)
            else:
                storm_active = False
                storm_reason = "auto_clear" if want_exit else "auto_idle"

        if storm_active:
            # Horizon pre-arm: slightly softer shell until full peak arrives
            env_for_shell = max(env_f, thr_f * 0.5 + 1.0)
            if horizon_enter and env_f < 1.85:
                env_for_shell = max(env_for_shell, 1.75)  # engage shell early but not max cut
            storm_scale = _storm_shell_physics(
                env_load=env_for_shell,
                thrash=thr_f,
                stability=stab,
                target=target,
                d_env=max(d_env_f, 0.15 if horizon_enter else 0.0),
                countermeasure=cm,
            )
            cool = True
            if open_traffic and env_f >= 1.85:
                open_traffic = False
                if conc_delta > 0:
                    conc_delta = 0
            if conc_delta > 1:
                conc_delta = 1
            # Beacons: same latch as storm — pull edge toward core under extreme
            beacon_active = True
            beacon_n = 5 + (1 if env_f >= 2.2 or thr_f >= 1.0 else 0)
            beacon_edge_frac = 0.22 if env_f < 2.4 else 0.26
            shell_depth = max(0.0, 1.0 - storm_scale)
            beacon_pull = float(
                min(0.22, 0.10 + 0.14 * shell_depth + 0.03 * min(1.0, thr_f / 1.5))
            )
            if horizon_enter and "horizon" in (storm_reason or reason):
                if note in ("hold", "nudge", "restore", "climb", "nudge_open", "restore_open"):
                    note = "horizon_pre_arm+beacons"
                elif "horizon" not in note:
                    note = f"{note}+horizon"
            elif note in ("hold", "nudge", "restore", "climb", "nudge_open", "restore_open"):
                note = "storm_auto+beacons"
            elif "+storm" not in note:
                note = f"{note}+storm+beacons"
            else:
                note = f"{note}+beacons"
        elif risk >= 0.35 and not deep_hurt:
            # Watch band: cool slightly without full shell (early posture)
            cool = True
            if note in ("hold", "nudge", "restore_open", "nudge_open", "climb"):
                note = "horizon_watch"
            open_traffic = False if thr_f >= 0.4 else open_traffic

    # --- Recovery desire: climb back fast after surge / env drop ---
    # Internal desire (rd) scales revive/open/concurrency; latch tracks window.
    env_falling = d_env is not None and float(d_env) < -0.08
    env_soft = env is not None and float(env) < RECOVERY_ENV_SOFT
    env_clear = env is not None and float(env) < RECOVERY_ENV_CLEAR
    # Soft load tolerates higher residual thrash; peak thrash still blocks residual climb
    thr_f = 0.0 if thr is None else float(thr)
    thr_ok_soft = thr is None or thr_f < (1.25 if env_clear else 0.90)

    # Arm recovery window only on real load cliffs / clear env after stress
    # (not every mild soft hour — that over-climbs mid-week and kills end-alive).
    if storm_latch is not None and thr_ok_soft:
        if env_falling and d_env is not None and float(d_env) < -0.25:
            storm_latch.arm_recovery(hold_steps)
        elif env_clear and (storm_active or env_falling):
            storm_latch.arm_recovery(hold_steps)

    armed = bool(storm_latch is not None and storm_latch.recovery_steps_left > 0)
    # True post-release climb
    latch_recovery = bool(storm_latch is not None and storm_latch.in_recovery)
    # Residual shell climb only while desire window is armed (scoped)
    residual_shell_climb = bool(storm_active and env_soft and thr_ok_soft and armed)
    hard_storm = bool(storm_active and env is not None and float(env) >= RECOVERY_ENV_SOFT + 0.15)

    if not hard_storm and (
        latch_recovery
        or residual_shell_climb
        or (env_falling and env_soft and thr_ok_soft)
        or (not storm_active and gap > 0.03 and calm_env and not deep_hurt and armed)
    ):
        if latch_recovery or residual_shell_climb or env_falling or (
            armed and gap > 0.05 and (gp is None or gp < 0.45)
        ):
            recovery_active = True
            # Desire band: revive scales with recovery_drive (capped — over-revive → thrash massacre)
            bonus = 1 + int(rd >= 1.25) + int(rd >= 1.80)
            revive_k = max(revive_k, min(5, 2 + bonus))
            # Already climbing hard / load rising again → pace (preserve end-alive)
            load_rising = d_env is not None and float(d_env) > 0.12
            climbing_ok = (gp is not None and gp >= 0.22) and (
                success_rate is None or float(success_rate) >= 0.42
            )
            if load_rising or climbing_ok:
                revive_k = min(revive_k, 2 if load_rising else 3)
            if env is None or env < 2.05:
                if not storm_active or env_clear or (env_soft and armed):
                    # Always cool while climbing; only open when thrash is controlled
                    cool = True if thr_f >= 0.25 or load_rising else cool
                    if thr_f < 0.55 and not load_rising:
                        open_traffic = True
                        conc_delta = max(conc_delta, 1 + int(rd >= 1.40))
                    else:
                        # climb via revive+cool first; open after thrash settles
                        open_traffic = False
                        conc_delta = min(conc_delta, 0)
            if budget_remaining is None or float(budget_remaining) >= 0.08:
                if note in (
                    "hold",
                    "nudge",
                    "cool",
                    "restore",
                    "climb",
                    "nudge_open",
                    "restore_open",
                    "protect",
                    "storm_auto+beacons",
                ):
                    note = "recovery_drive"
                elif "recovery" not in note:
                    note = f"{note}+recovery"

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
        beacon_active=bool(beacon_active),
        beacon_n=int(beacon_n),
        beacon_edge_frac=float(beacon_edge_frac),
        beacon_pull=float(beacon_pull),
        recovery_active=bool(recovery_active),
        pre_arm=bool(horizon_pre_arm or horizon_imminent or risk >= 0.55),
        surge_risk=float(risk),
        horizon_reasons=str(horizon_reasons or ""),
    )


def apply_shield(env_load: float, plan: ActionPlan) -> float:
    """Felt load after base shield × storm shell."""
    return float(max(0.0, env_load * plan.felt_scale()))


def apply_beacons_to_swarm(agents: list, plan: ActionPlan, *, ceiling: float = 0.97) -> int:
    """
    Kernel-side beacon pull: top-coherence agents attract edge (low coherence).
    Same storm latch — only when plan.beacon_active.
    Returns number of edge agents pulled.
    Outer systems can mirror: prefer healthy workers, drain worst tail.
    """
    if not plan.beacon_active or plan.beacon_pull <= 0 or plan.beacon_n <= 0:
        return 0
    n = len(agents)
    if n < 3:
        return 0
    try:
        import numpy as np
    except ImportError:
        return 0

    order = np.argsort([float(getattr(a, "coherence", 0.5)) for a in agents])
    n_edge = max(1, int(round(n * float(plan.beacon_edge_frac or 0.22))))
    n_beac = max(1, min(int(plan.beacon_n), n // 3))
    edge_idx = [int(i) for i in order[:n_edge]]
    beac_idx = [int(i) for i in order[-n_beac:]]
    core = float(np.mean([agents[i].coherence for i in beac_idx]))
    pull = float(plan.beacon_pull)
    for i in edge_idx:
        a = agents[i]
        a.coherence = float(
            max(0.0, min(ceiling, (1.0 - pull) * a.coherence + pull * core))
        )
        if hasattr(a, "flux"):
            a.flux = float(a.flux * 0.90)
        if hasattr(a, "velocity"):
            a.velocity *= 0.92
    # small core tax — beacons spend energy
    tax = 0.006 * pull / 0.15
    for i in beac_idx:
        agents[i].coherence = float(max(0.0, min(ceiling, agents[i].coherence - tax)))
    return len(edge_idx)
