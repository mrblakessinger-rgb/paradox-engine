"""
Near-blackout curriculum — progress watch (1+2+3+4)
====================================================
1) Varied surge shapes (length / second-spike timing) — same power floor ~0.18–0.28
2) Harder scar rewards for settle-alive + recover climb
3) Damper / viscosity soft-cap ~2.3 (no more pumping to 2.5 dead zone)
4) Shadow track: 429 / partial-outage style env at SAME floor (no lower power yet)

3 cycles × multi-shape curriculum + shadow eval each cycle.
Frozen control for noise.

  python real_world/near_blackout_curriculum.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K
from nodes.actuate import apply_shield, plan_actions
from nodes.ingest import from_api

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = K.TARGET_STABILITY
N_CYCLES = 3
POWER_LO, POWER_HI = 0.18, 0.28
# (3) soft caps — stop dead-zone pumping
DAMPER_SOFT_CAP = 2.30
VISC_SOFT_CAP = 2.30
REPAIR_SOFT_CAP = 2.40
CM_SOFT_CAP = 1.85


# ---------------------------------------------------------------------------
# World (shared)
# ---------------------------------------------------------------------------
class FleetWorld:
    def __init__(self, n_clients=32, budget=14.0, rng=None):
        self.n_clients = n_clients
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n_clients, dtype=bool)
        self.client_fail = np.zeros(n_clients, dtype=int)
        self.recent_ok: list[int] = []
        self.recent_goodput: list[float] = []
        self.retries = 0.0
        self.power = 1.0
        self.mode = "power"  # power | api429

    def rolling_success(self) -> float:
        return 0.55 if not self.recent_ok else float(np.mean(self.recent_ok[-80:]))

    def rolling_goodput(self) -> float:
        return 0.3 if not self.recent_goodput else float(np.mean(self.recent_goodput[-24:]))

    def step(self, interference: float) -> dict:
        if self.mode == "api429":
            # (4) shadow: power stays high; capacity dies via 429-style I + thrash
            cap_scale = max(0.05, 1.0 - 0.34 * interference)
            capacity = self.base_budget * cap_scale
            flake_extra = 0.0
        else:
            cap_scale = float(np.clip(self.power, 0, 1)) * max(0.04, 1.0 - 0.22 * interference)
            capacity = self.base_budget * cap_scale
            flake_extra = 0.48 * (1.0 - self.power)

        active = list(np.where(self.alive)[0])
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0:
            self.recent_goodput.append(0.0)
            return self._snap(0.0, 0, capacity, 0)

        serve = int(min(demand, max(0, round(capacity))))
        flake = float(np.clip(0.06 + 0.13 * interference + flake_extra, 0.05, 0.88))
        ok = fails = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            if i < serve and self.rng.random() > flake:
                ok += 1
                self.client_fail[c] = max(0, self.client_fail[c] - 1)
                self.recent_ok.append(1)
            else:
                fails += 1
                self.client_fail[c] += 1
                self.recent_ok.append(0)
                self.retries = min(3.2, self.retries + 0.045)
                if self.client_fail[c] >= 6 and self.rng.random() < 0.40:
                    self.alive[c] = False
        if fails == 0 and (self.power > 0.65 or self.mode == "api429" and interference < 1.5):
            self.retries = max(0.0, self.retries - 0.10)
        if len(self.recent_ok) > 400:
            self.recent_ok = self.recent_ok[-400:]
        gp = ok / self.n_clients
        self.recent_goodput.append(gp)
        if len(self.recent_goodput) > 100:
            self.recent_goodput = self.recent_goodput[-100:]
        return self._snap(gp, int(np.sum(self.alive)), capacity, demand)

    def _snap(self, step_gp, n_alive, capacity, demand):
        br = float(np.clip(capacity / max(self.base_budget, 1e-6), 0, 1))
        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "step_goodput": step_gp,
            "n_alive": n_alive,
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "power": self.power,
            "budget_remaining": br,
        }

    def quarantine_worst(self, k=1):
        alive_idx = np.where(self.alive)[0]
        if len(alive_idx) == 0:
            return
        order = sorted(alive_idx, key=lambda i: -self.client_fail[i])
        for i in order[:k]:
            self.alive[i] = False

    def revive(self, k=1):
        for i in np.where(~self.alive)[0][:k]:
            self.alive[i] = True
            self.client_fail[i] = 0


def apply_plan(world: FleetWorld, plan) -> None:
    if plan.cool_retries:
        mul = 0.62 if plan.storm_active else 0.72
        if world.mode == "power" and world.power < 0.35:
            mul = min(mul, 0.55)
        world.retries = max(0.0, world.retries * mul)
    if plan.quarantine_k > 0:
        world.quarantine_worst(plan.quarantine_k)
    if plan.revive_k > 0:
        ok_power = world.mode == "api429" or world.power >= 0.22
        if ok_power:
            k = plan.revive_k
            if plan.storm_active and (world.mode == "power" and world.power < 0.55):
                k = min(k, 1)
            world.revive(k)
    if plan.concurrency_delta < 0 and world.retries > 0:
        world.retries = max(0.0, world.retries + 0.04 * plan.concurrency_delta)


# ---------------------------------------------------------------------------
# (1) Curriculum shapes — same floor, different timing
# ---------------------------------------------------------------------------
def shape_A_classic(steps=140):
    """Baseline near-blackout shape."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 20:
            env.append(1.15); power.append(1.0); phase.append("calm")
        elif t < 28:
            env.append(1.8 + 0.05 * (t - 20))
            power.append(float(np.clip(0.70 - 0.04 * (t - 20), POWER_LO + 0.05, 1)))
            phase.append("brownout")
        elif t < 48:
            env.append(2.85)
            power.append(float(np.clip(POWER_LO + 0.04 * ((t % 3) == 0), POWER_LO, POWER_HI)))
            phase.append("SURGE")
        elif t < 62:
            env.append(2.35)
            power.append(float(np.clip(0.40 + 0.12 * np.sin((t - 48) * 0.9), POWER_LO, 0.65)))
            phase.append("aftershock")
        elif t < 78:
            env.append(2.75)
            power.append(float(POWER_LO + 0.06 if t % 2 == 0 else POWER_HI))
            phase.append("SURGE2")
        elif t < 100:
            env.append(1.55)
            power.append(float(min(1.0, 0.48 + 0.024 * (t - 78))))
            phase.append("recover")
        else:
            env.append(1.2); power.append(1.0); phase.append("settle")
    return env, power, phase, "A_classic"


def shape_B_long_surge(steps=140):
    """Longer first surge, delayed second spike."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 15:
            env.append(1.1); power.append(1.0); phase.append("calm")
        elif t < 22:
            env.append(1.9); power.append(0.55); phase.append("brownout")
        elif t < 58:  # long SURGE
            env.append(2.9)
            power.append(float(np.clip(POWER_LO + 0.03 * ((t % 4) == 0), POWER_LO, POWER_HI)))
            phase.append("SURGE")
        elif t < 70:
            env.append(2.2); power.append(0.45); phase.append("aftershock")
        elif t < 88:  # late SURGE2
            env.append(2.8)
            power.append(float(POWER_HI if t % 2 else POWER_LO))
            phase.append("SURGE2")
        elif t < 110:
            env.append(1.5); power.append(min(1.0, 0.42 + 0.028 * (t - 88))); phase.append("recover")
        else:
            env.append(1.15); power.append(1.0); phase.append("settle")
    return env, power, phase, "B_long_surge"


def shape_C_double_early(steps=140):
    """Two hard hits early; long recover."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 12:
            env.append(1.2); power.append(1.0); phase.append("calm")
        elif t < 18:
            env.append(2.0); power.append(0.5); phase.append("brownout")
        elif t < 32:
            env.append(2.95)
            power.append(float(POWER_LO + 0.02 * (t % 2)))
            phase.append("SURGE")
        elif t < 40:
            env.append(2.1); power.append(0.38); phase.append("aftershock")
        elif t < 54:
            env.append(2.9); power.append(float(POWER_LO + 0.05)); phase.append("SURGE2")
        elif t < 95:
            env.append(1.45); power.append(min(1.0, 0.35 + 0.016 * (t - 54))); phase.append("recover")
        else:
            env.append(1.1); power.append(1.0); phase.append("settle")
    return env, power, phase, "C_double_early"


def shape_D_flicker_plateau(steps=140):
    """No clean second spike — long flicker at floor."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 18:
            env.append(1.15); power.append(1.0); phase.append("calm")
        elif t < 26:
            env.append(1.85); power.append(0.6); phase.append("brownout")
        elif t < 75:
            env.append(2.7 + 0.15 * np.sin(t * 0.4))
            power.append(float(np.clip(POWER_LO + 0.08 * abs(np.sin(t * 0.55)), POWER_LO, POWER_HI)))
            phase.append("SURGE" if t < 55 else "SURGE2")
        elif t < 100:
            env.append(1.6); power.append(min(1.0, 0.5 + 0.02 * (t - 75))); phase.append("recover")
        else:
            env.append(1.2); power.append(1.0); phase.append("settle")
    return env, power, phase, "D_flicker"


def shape_E_short_brutal(steps=140):
    """Short calm, brutal short double, long settle."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 10:
            env.append(1.0); power.append(1.0); phase.append("calm")
        elif t < 16:
            env.append(2.1); power.append(0.48); phase.append("brownout")
        elif t < 30:
            env.append(3.0); power.append(POWER_LO); phase.append("SURGE")
        elif t < 36:
            env.append(2.4); power.append(0.42); phase.append("aftershock")
        elif t < 48:
            env.append(2.95); power.append(POWER_LO + 0.04); phase.append("SURGE2")
        elif t < 85:
            env.append(1.4); power.append(min(1.0, 0.4 + 0.018 * (t - 48))); phase.append("recover")
        else:
            env.append(1.1); power.append(1.0); phase.append("settle")
    return env, power, phase, "E_short_brutal"


CURRICULUM = [
    shape_A_classic,
    shape_B_long_surge,
    shape_C_double_early,
    shape_D_flicker_plateau,
    shape_E_short_brutal,
]


def shape_shadow_429(steps=140):
    """
    (4) Partial outage / 429 shadow at SAME stress band as near-blackout
    without lowering power (power=1; I carries the pain).
    """
    env, power, phase = [], [], []
    for t in range(steps):
        power.append(1.0)
        if t < 20:
            env.append(1.2); phase.append("calm")
        elif t < 30:
            env.append(2.0); phase.append("brownout")  # rising 429
        elif t < 55:
            env.append(2.85); phase.append("SURGE")  # hard 429 plateau
        elif t < 70:
            env.append(2.2 + 0.4 * abs(np.sin(t))); phase.append("aftershock")
        elif t < 90:
            env.append(2.7); phase.append("SURGE2")
        elif t < 115:
            env.append(1.5); phase.append("recover")
        else:
            env.append(1.15); phase.append("settle")
    return env, power, phase, "shadow_429"


# ---------------------------------------------------------------------------
# (3) Soft-cap intuition
# ---------------------------------------------------------------------------
def soft_cap_intuition(paradox: K.Paradox) -> None:
    caps = {
        "damper_bias": DAMPER_SOFT_CAP,
        "viscosity_bias": VISC_SOFT_CAP,
        "repair_bias": REPAIR_SOFT_CAP,
        "countermeasure_invest": CM_SOFT_CAP,
    }
    for k, cap in caps.items():
        if k in paradox.intuition:
            paradox.intuition[k] = float(min(float(paradox.intuition[k]), cap))
    # floor explore so we don't freeze
    if "explore_bias" in paradox.intuition:
        paradox.intuition["explore_bias"] = float(
            np.clip(paradox.intuition["explore_bias"], 0.06, 0.45)
        )


def learn_from_episode(paradox: K.Paradox, scars: list, meta: dict) -> dict:
    """
    (2) Stronger rewards for settle-alive + recover climb.
    (3) Soft caps after nudges.
    """
    paradox.absorb_episode(scars, episode_meta=meta)
    report = paradox.compress_scars_to_wisdom(max_intuition_delta=0.07)

    # count scar classes
    reasons = [str(s.get("reason", "")) for s in scars]
    n_recover = sum(1 for r in reasons if "climb_recover" in r or "climb_calm" in r)
    n_settle_ok = sum(1 for r in reasons if "settle_alive" in r)
    n_surge_hold = sum(1 for r in reasons if "surge_hold" in r)
    n_tighten = sum(1 for r in reasons if "tighten" in r)

    def bump(k, d, lo=0.05, hi=2.5):
        old = float(paradox.intuition.get(k, 1.0))
        paradox.intuition[k] = float(np.clip(old + d, lo, hi))

    # (2) HARD rewards — recover + settle population
    end_alive = float(meta.get("alive_end", 0))
    rec_gp = float(meta.get("gp_recover", 0) or 0)
    settle_gp = float(meta.get("gp_settle", 0) or 0)

    if n_recover >= 2 or rec_gp >= 0.08:
        bump("repair_bias", 0.04)
        bump("pairing_strength", 0.03)
        bump("floor_boost", 0.015, 0.02, 0.35)
    if n_settle_ok >= 1 or end_alive >= 14:
        bump("repair_bias", 0.035)
        bump("pairing_strength", 0.025)
        bump("failure_respect", 0.015)
    if end_alive >= 16 and settle_gp >= 0.25:
        bump("repair_bias", 0.02)
        bump("countermeasure_invest", 0.02)

    # survive surge without total wipe
    if n_surge_hold >= 2 or float(meta.get("alive_min_surge", 0) or 0) >= 1:
        bump("countermeasure_invest", 0.03)
        bump("damper_bias", 0.02)  # modest — soft-capped later

    # thrash pain — damper but capped
    if n_tighten >= 4:
        bump("damper_bias", 0.025)
        bump("failure_respect", 0.02)
        bump("explore_bias", -0.008, 0.06, 0.45)

    if meta.get("first_hard_break") is not None:
        bump("damper_bias", 0.02)
        bump("viscosity_bias", 0.015)

    soft_cap_intuition(paradox)
    report["end_alive"] = end_alive
    report["n_recover_scars"] = n_recover
    report["n_settle_ok"] = n_settle_ok
    return report


# ---------------------------------------------------------------------------
# Episode runner
# ---------------------------------------------------------------------------
def run_episode(
    *,
    paradox: K.Paradox,
    seed: int,
    env_sched,
    power_sched,
    phases,
    shape_name: str,
    mode: str = "power",  # power | api429
    learn: bool = True,
    storm_mode: str = "auto",
) -> dict:
    world = FleetWorld(rng=np.random.default_rng(seed))
    world.mode = mode
    k_rng = np.random.default_rng(seed + 91)
    agents = K.make_swarm(k_rng)
    paradox.install_drivers(agents)
    ambient = 0.0
    stab = 0.88
    prev_env = env_sched[0]
    rows = []
    scars = []
    first_soft = first_hard = None

    for t, (env_I, pwr) in enumerate(zip(env_sched, power_sched)):
        world.power = 1.0 if mode == "api429" else pwr
        d_env = env_I - prev_env
        thrash_sig = world.retries + (0.0 if mode == "api429" else (1.0 - world.power) * 1.3)
        env_for_plan = env_I + (0.0 if mode == "api429" else (1.0 - world.power) * 1.1)
        plan = plan_actions(
            stab,
            success_rate=world.rolling_success(),
            goodput=world.rolling_goodput(),
            env_load=env_for_plan,
            thrash=thrash_sig,
            storm_mode=storm_mode,  # type: ignore[arg-type]
            d_env=d_env,
            budget_remaining=float(np.clip(world.power if mode == "power" else max(0.05, 1.0 - 0.3 * env_I), 0, 1)),
            target=TARGET,
        )
        felt = apply_shield(env_I, plan)
        m = world.step(felt)
        apply_plan(world, plan)

        I = from_api(
            world.rolling_goodput(),
            env_I + (0 if mode == "api429" else (1.0 - world.power)),
            retries=world.retries,
            budget_remaining=float(np.clip(m["budget_remaining"], 0, 1)),
        )
        for a in agents:
            a.step(I, ambient, k_rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, k_rng)
        paradox.install_drivers(agents)
        soft_cap_intuition(paradox)  # keep installs from exceeding soft caps via blend
        # re-apply soft cap on paradox after install doesn't change paradox; clamp agents lightly
        for a in agents:
            for k, cap in (("damper_bias", DAMPER_SOFT_CAP), ("viscosity_bias", VISC_SOFT_CAP)):
                if k in a.instinct:
                    a.instinct[k] = float(min(float(a.instinct[k]), cap))

        stab = K.stability(agents)
        ph = phases[t]
        rows.append({**m, "env_I": env_I, "stab": stab, "storm": plan.storm_active, "phase": ph})

        # --- scars (2: richer recover/settle tags) ---
        if ph in ("SURGE", "SURGE2") and m["n_alive"] >= 2:
            scars.append({"reason": "surge_hold", "alive": m["n_alive"], "gp": m["rolling_goodput"]})
        if ph in ("SURGE", "SURGE2", "brownout") and m["rolling_goodput"] < 0.10:
            scars.append({"reason": "tighten_storm", "gp": m["rolling_goodput"], "phase": ph})
        if m["n_alive"] < 8:
            scars.append({"reason": "tighten_floor", "alive": m["n_alive"]})
        if ph == "recover" and m["rolling_goodput"] >= 0.06:
            scars.append({"reason": "climb_recover", "gp": m["rolling_goodput"], "alive": m["n_alive"]})
        if ph == "recover" and m["n_alive"] >= 10:
            scars.append({"reason": "climb_recover", "alive": m["n_alive"]})
        if ph == "settle" and m["n_alive"] >= 12:
            scars.append({"reason": "settle_alive", "alive": m["n_alive"], "gp": m["rolling_goodput"]})
        if ph == "settle" and m["rolling_goodput"] >= 0.22:
            scars.append({"reason": "climb_calm", "gp": m["rolling_goodput"]})
        if stab < 0.85 and first_soft is None:
            first_soft = t
            scars.append({"reason": "soft_floor", "stab": stab})
        if (stab < 0.70 or m["n_alive"] < 3) and first_hard is None:
            first_hard = t
            scars.append({"reason": "hard_break_threat", "alive": m["n_alive"]})

        prev_env = env_I

    gp = np.array([r["rolling_goodput"] for r in rows])
    alive = np.array([r["n_alive"] for r in rows], float)
    ph = np.array([r["phase"] for r in rows])
    hard = np.isin(ph, ["SURGE", "SURGE2"])
    rec = ph == "recover"
    settle = ph == "settle"
    late_n = max(1, len(rows) // 5)

    def pmean(mask, arr):
        return float(np.mean(arr[mask])) if np.any(mask) else float("nan")

    meta = {
        "alive_end": float(alive[-1]),
        "gp_recover": pmean(rec, gp),
        "gp_settle": pmean(settle, gp),
        "alive_min_surge": float(np.min(alive[hard])) if np.any(hard) else 0.0,
        "first_soft_break": first_soft,
        "first_hard_break": first_hard if float(np.min(alive)) < 2 else None,
        "recovery_peak": float(np.max(gp[rec])) if np.any(rec) else float(np.max(gp)),
        "recovery_late": pmean(settle, gp),
        "survived_long_hell": float(np.mean(alive[hard])) >= 0.8 if np.any(hard) else True,
        "final_alive": float(alive[-1]) >= 6,
    }

    learn_report = {}
    if learn:
        if len(scars) > 100:
            scars = scars[-100:]
        learn_report = learn_from_episode(paradox, scars, meta)

    return {
        "shape": shape_name,
        "mode": mode,
        "gp_mean": float(np.mean(gp)),
        "gp_late": float(np.mean(gp[-late_n:])),
        "gp_surge": pmean(hard, gp),
        "gp_recover": pmean(rec, gp),
        "gp_settle": pmean(settle, gp),
        "alive_surge": pmean(hard, alive),
        "alive_min_surge": float(np.min(alive[hard])) if np.any(hard) else float("nan"),
        "alive_recover": pmean(rec, alive),
        "alive_end": float(alive[-1]),
        "alive_min": float(np.min(alive)),
        "stab_late": float(np.mean([r["stab"] for r in rows[-late_n:]])),
        "storm_frac": float(np.mean([1.0 if r["storm"] else 0.0 for r in rows])),
        "intuition": {
            k: float(paradox.intuition[k])
            for k in (
                "damper_bias",
                "repair_bias",
                "viscosity_bias",
                "countermeasure_invest",
                "failure_respect",
                "pairing_strength",
                "explore_bias",
            )
            if k in paradox.intuition
        },
        "learn_report": {
            "n_scars": learn_report.get("n_scars", len(scars)),
            "n_recover": learn_report.get("n_recover_scars", 0),
            "n_settle_ok": learn_report.get("n_settle_ok", 0),
        },
        "gp_series": gp.tolist(),
        "alive_series": alive.tolist(),
    }


def main() -> int:
    print("=" * 70)
    print(" NEAR-BLACKOUT CURRICULUM (1 shapes · 2 settle rewards · 3 soft-caps · 4 shadow 429)")
    print(f" power floor {POWER_LO}–{POWER_HI} · damper soft-cap {DAMPER_SOFT_CAP}")
    print("=" * 70)

    seeds = [7, 13, 21, 42]
    # Each cycle: all 5 shapes + 1 shadow 429
    learn_cycle = {c: [] for c in range(1, N_CYCLES + 1)}
    shadow_cycle = {c: [] for c in range(1, N_CYCLES + 1)}
    frozen_cycle = {c: [] for c in range(1, N_CYCLES + 1)}

    print("\n[LEARN] 5 surge shapes/cycle + shadow 429, scars carry")
    for seed in seeds:
        paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
        soft_cap_intuition(paradox)
        for c in range(1, N_CYCLES + 1):
            shape_rows = []
            for i, shape_fn in enumerate(CURRICULUM):
                env, pwr, phases, name = shape_fn()
                r = run_episode(
                    paradox=paradox,
                    seed=seed * 100 + c * 10 + i,
                    env_sched=env,
                    power_sched=pwr,
                    phases=phases,
                    shape_name=name,
                    mode="power",
                    learn=True,
                )
                shape_rows.append(r)
            # mean across shapes this cycle for this seed
            def mean_shapes(key):
                return float(np.mean([x[key] for x in shape_rows]))

            pack = {
                "seed": seed,
                "cycle": c,
                "gp_surge": mean_shapes("gp_surge"),
                "alive_surge": mean_shapes("alive_surge"),
                "alive_min_surge": mean_shapes("alive_min_surge"),
                "gp_recover": mean_shapes("gp_recover"),
                "alive_recover": mean_shapes("alive_recover"),
                "gp_settle": mean_shapes("gp_settle"),
                "alive_end": mean_shapes("alive_end"),
                "gp_late": mean_shapes("gp_late"),
                "stab_late": mean_shapes("stab_late"),
                "intuition": shape_rows[-1]["intuition"],
                "shapes": {x["shape"]: {"gp_surge": x["gp_surge"], "alive_end": x["alive_end"]} for x in shape_rows},
            }
            learn_cycle[c].append(pack)

            # (4) shadow 429 after power shapes
            env, pwr, phases, name = shape_shadow_429()
            sh = run_episode(
                paradox=paradox,
                seed=seed * 100 + c * 10 + 99,
                env_sched=env,
                power_sched=pwr,
                phases=phases,
                shape_name=name,
                mode="api429",
                learn=True,
            )
            shadow_cycle[c].append(sh)

            print(
                f"  seed={seed} c{c}  "
                f"surge_gp={pack['gp_surge']:.3f} end_alive={pack['alive_end']:.1f}  "
                f"settle_gp={pack['gp_settle']:.3f} rec_gp={pack['gp_recover']:.3f}  "
                f"shadow_gp_late={sh['gp_late']:.3f} sh_alive={sh['alive_end']:.0f}  "
                f"damp={pack['intuition'].get('damper_bias',0):.2f} "
                f"repair={pack['intuition'].get('repair_bias',0):.2f} "
                f"cm={pack['intuition'].get('countermeasure_invest',0):.2f}"
            )

    print("\n[FROZEN] same curriculum, Paradox reset each cycle")
    for seed in seeds:
        for c in range(1, N_CYCLES + 1):
            paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
            soft_cap_intuition(paradox)
            shape_rows = []
            for i, shape_fn in enumerate(CURRICULUM):
                env, pwr, phases, name = shape_fn()
                r = run_episode(
                    paradox=paradox,
                    seed=seed * 100 + c * 10 + i + 5000,
                    env_sched=env,
                    power_sched=pwr,
                    phases=phases,
                    shape_name=name,
                    mode="power",
                    learn=False,
                )
                shape_rows.append(r)
            pack = {
                "gp_surge": float(np.mean([x["gp_surge"] for x in shape_rows])),
                "alive_end": float(np.mean([x["alive_end"] for x in shape_rows])),
                "gp_settle": float(np.mean([x["gp_settle"] for x in shape_rows])),
                "gp_recover": float(np.mean([x["gp_recover"] for x in shape_rows])),
            }
            frozen_cycle[c].append(pack)
        print(
            f"  seed={seed} frozen end_alive c1={frozen_cycle[1][-1]['alive_end']:.1f} "
            f"c3={frozen_cycle[3][-1]['alive_end']:.1f}"
        )

    def L(c, k):
        return float(np.mean([x[k] for x in learn_cycle[c]]))

    def F(c, k):
        return float(np.mean([x[k] for x in frozen_cycle[c]]))

    def S(c, k):
        return float(np.mean([x[k] for x in shadow_cycle[c]]))

    print("\n[LEARN PROGRESS]")
    print(f"  {'metric':18s}  c1      c2      c3     Δc3−c1  frozenΔ")
    for k in ("gp_surge", "alive_surge", "gp_recover", "alive_recover", "gp_settle", "alive_end", "gp_late"):
        dL = L(3, k) - L(1, k)
        dF = (F(3, k) - F(1, k)) if k in frozen_cycle[1][0] else float("nan")
        print(f"  {k:18s}  {L(1,k):6.3f}  {L(2,k):6.3f}  {L(3,k):6.3f}  {dL:+.3f}  {dF:+.3f}")

    print("\n[SHADOW 429 PROGRESS] (same stress band, power=1)")
    for k in ("gp_late", "alive_end", "gp_surge", "gp_settle"):
        print(f"  shadow {k:14s}  c1={S(1,k):.3f}  c3={S(3,k):.3f}  Δ={S(3,k)-S(1,k):+.3f}")

    # intuition drift
    print("\n[INTUITION c1 → c3 mean]")
    for k in ("damper_bias", "repair_bias", "countermeasure_invest", "pairing_strength", "failure_respect"):
        v1 = float(np.mean([x["intuition"].get(k, 0) for x in learn_cycle[1]]))
        v3 = float(np.mean([x["intuition"].get(k, 0) for x in learn_cycle[3]]))
        print(f"  {k:24s}  {v1:.3f} → {v3:.3f}  (cap check damper≤{DAMPER_SOFT_CAP})")

    d_alive = L(3, "alive_end") - L(1, "alive_end")
    d_settle = L(3, "gp_settle") - L(1, "gp_settle")
    d_rec = L(3, "gp_recover") - L(1, "gp_recover")
    d_sh = S(3, "gp_late") - S(1, "gp_late")
    d_f_alive = F(3, "alive_end") - F(1, "alive_end")
    damp3 = float(np.mean([x["intuition"].get("damper_bias", 0) for x in learn_cycle[3]]))

    gains = []
    if d_alive > d_f_alive + 0.8:
        gains.append("end_alive")
    if d_settle > 0.01:
        gains.append("settle_gp")
    if d_rec > 0.01:
        gains.append("recover_gp")
    if d_sh > 0.015:
        gains.append("shadow_429")
    if damp3 <= DAMPER_SOFT_CAP + 0.02:
        gains.append("damper_capped_ok")

    if len(gains) >= 2 and "end_alive" in gains:
        verdict = (
            "CURRICULUM_HELPS: multi-shape + settle rewards move survival/recovery "
            "beyond frozen noise. Safe to consider inching floor later (e.g. 0.15–0.22)."
        )
    elif gains:
        verdict = (
            f"CURRICULUM_PARTIAL gains={gains}. Keep this floor; another curriculum pass "
            "or more seeds before lowering power."
        )
    else:
        verdict = (
            "CURRICULUM_FLAT still: shell dominates; extend shape diversity or real log replay "
            "before lowering floor."
        )
    print(f"\n  VERDICT → {verdict}")
    print(f"  gains tagged: {gains}")

    # plots
    fig, axes = plt.subplots(2, 1, figsize=(10, 7))
    ax = axes[0]
    xs = [1, 2, 3]
    for key, lab, col in [
        ("alive_end", "end alive /32", "#40d0ff"),
        ("gp_settle", "settle gp", "#2ecc71"),
        ("gp_recover", "recover gp", "#f39c12"),
        ("gp_surge", "surge gp", "#e74c3c"),
    ]:
        ys = []
        for c in xs:
            v = L(c, key)
            ys.append(v / 32.0 if "alive" in key else v)
        ax.plot(xs, ys, "o-", label=lab, color=col, lw=2)
    ax.set_xticks(xs)
    ax.set_xlabel("cycle")
    ax.set_ylabel("goodput or alive frac")
    ax.set_title("Curriculum learn progress (power floor 0.18–0.28)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(xs, [S(c, "gp_late") for c in xs], "s-", color="#9b59b6", lw=2, label="shadow 429 late gp")
    ax2.plot(xs, [S(c, "alive_end") / 32 for c in xs], "s-", color="#1abc9c", lw=2, label="shadow 429 end alive")
    ax2.set_xticks(xs)
    ax2.set_xlabel("cycle")
    ax2.set_title("(4) Shadow 429 track at same stress band")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)
    fig.tight_layout()
    png = OUT / "near_blackout_curriculum.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # per-shape c1 vs c3 for one seed path — aggregate shape means from last packs
    fig2, ax = plt.subplots(figsize=(10, 5))
    shape_names = ["A_classic", "B_long_surge", "C_double_early", "D_flicker", "E_short_brutal"]
    # recompute shape-level from stored packs
    c1_end = []
    c3_end = []
    for sn in shape_names:
        e1 = [p["shapes"][sn]["alive_end"] for p in learn_cycle[1] if sn in p["shapes"]]
        e3 = [p["shapes"][sn]["alive_end"] for p in learn_cycle[3] if sn in p["shapes"]]
        c1_end.append(float(np.mean(e1)) if e1 else 0)
        c3_end.append(float(np.mean(e3)) if e3 else 0)
    x = np.arange(len(shape_names))
    ax.bar(x - 0.2, c1_end, 0.4, label="c1 end alive", color="#888")
    ax.bar(x + 0.2, c3_end, 0.4, label="c3 end alive", color="#2ecc71")
    ax.set_xticks(x)
    ax.set_xticklabels(shape_names, rotation=15, ha="right")
    ax.set_ylabel("end alive")
    ax.set_title("(1) Per-shape survival c1 vs c3")
    ax.legend()
    ax.grid(True, alpha=0.25, axis="y")
    fig2.tight_layout()
    png2 = OUT / "near_blackout_curriculum_shapes.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "near_blackout_curriculum_v1",
        "features": [
            "varied surge shapes",
            "settle/recover scar rewards",
            "damper soft-cap 2.3",
            "shadow 429 track",
        ],
        "power_band": [POWER_LO, POWER_HI],
        "soft_caps": {
            "damper": DAMPER_SOFT_CAP,
            "viscosity": VISC_SOFT_CAP,
            "repair": REPAIR_SOFT_CAP,
            "countermeasure": CM_SOFT_CAP,
        },
        "learn": {str(c): {k: L(c, k) for k in (
            "gp_surge", "alive_surge", "gp_recover", "alive_recover",
            "gp_settle", "alive_end", "gp_late",
        )} for c in (1, 2, 3)},
        "frozen": {str(c): {k: F(c, k) for k in ("gp_surge", "alive_end", "gp_settle", "gp_recover")} for c in (1, 2, 3)},
        "shadow_429": {str(c): {k: S(c, k) for k in ("gp_late", "alive_end", "gp_surge", "gp_settle")} for c in (1, 2, 3)},
        "delta_learn_c3_c1": {
            "alive_end": d_alive,
            "gp_settle": d_settle,
            "gp_recover": d_rec,
            "shadow_gp_late": d_sh,
        },
        "delta_frozen_alive_end": d_f_alive,
        "gains": gains,
        "verdict": verdict,
    }
    js = OUT / "near_blackout_curriculum_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
