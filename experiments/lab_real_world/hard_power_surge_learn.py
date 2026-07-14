"""
Hard power surge LEARN — train just under blackout × 3 cycles
=============================================================
Full blackout (power≈0) is unwinnable for goodput — we know.
This trains on a *near-blackout floor* so the fleet can still act:

  power floor ≈ 0.18–0.28 during "hard" windows (not 0.04)
  same brownout → surge → aftershock → surge2 → recover shape

3 cycles share one Paradox (scar → wisdom → install).
Compare c1 vs c2 vs c3 with storm_mode=auto.

Control: frozen PROMOTED (reset Paradox each cycle) to separate luck from learn.

  python real_world/hard_power_surge_learn.py
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
# Just under full blackout — room to act, still brutal
POWER_FLOOR = 0.20
POWER_SURGE_PEAK_LOW = 0.18
POWER_SURGE_PEAK_HI = 0.28


class SurgeWorld:
    def __init__(self, n_clients: int = 32, budget: float = 14.0, rng: np.random.Generator | None = None):
        self.n_clients = n_clients
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n_clients, dtype=bool)
        self.client_fail = np.zeros(n_clients, dtype=int)
        self.recent_ok: list[int] = []
        self.recent_goodput: list[float] = []
        self.retries = 0.0
        self.power = 1.0

    def rolling_success(self) -> float:
        if not self.recent_ok:
            return 0.55
        return float(np.mean(self.recent_ok[-80:]))

    def rolling_goodput(self) -> float:
        if not self.recent_goodput:
            return 0.3
        return float(np.mean(self.recent_goodput[-24:]))

    def step(self, interference: float) -> dict:
        cap_scale = float(np.clip(self.power, 0.0, 1.0)) * max(0.02, 1.0 - 0.22 * interference)
        capacity = self.base_budget * cap_scale
        active = list(np.where(self.alive)[0])
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0:
            self.recent_goodput.append(0.0)
            return self._snap(0.0, 0, capacity, 0)

        serve = int(min(demand, max(0, round(capacity))))
        flake = float(
            np.clip(0.06 + 0.12 * interference + 0.50 * (1.0 - self.power), 0.05, 0.88)
        )
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
        if fails == 0 and self.power > 0.65:
            self.retries = max(0.0, self.retries - 0.10)
        if len(self.recent_ok) > 400:
            self.recent_ok = self.recent_ok[-400:]
        step_gp = ok / self.n_clients
        self.recent_goodput.append(step_gp)
        if len(self.recent_goodput) > 100:
            self.recent_goodput = self.recent_goodput[-100:]
        return self._snap(step_gp, int(np.sum(self.alive)), capacity, demand)

    def _snap(self, step_gp, n_alive, capacity, demand):
        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "step_goodput": step_gp,
            "n_alive": n_alive,
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "power": self.power,
            "budget_remaining": float(np.clip(self.power * max(0.05, capacity / max(self.base_budget, 1e-6)), 0, 1)),
        }

    def quarantine_worst(self, k: int = 1):
        alive_idx = np.where(self.alive)[0]
        if len(alive_idx) == 0:
            return
        order = sorted(alive_idx, key=lambda i: -self.client_fail[i])
        for i in order[:k]:
            self.alive[i] = False

    def revive(self, k: int = 1):
        dead = np.where(~self.alive)[0]
        for i in dead[:k]:
            self.alive[i] = True
            self.client_fail[i] = 0


def timeline_near_blackout(steps: int = 140) -> tuple[list[float], list[float], list[str]]:
    """Same shape as hard surge, but power floor just under blackout."""
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 20:
            env.append(1.15)
            power.append(1.0)
            phase.append("calm")
        elif t < 28:
            env.append(1.8 + 0.05 * (t - 20))
            # brownout down toward floor, not through it
            power.append(float(np.clip(0.70 - 0.04 * (t - 20), POWER_FLOOR + 0.05, 1.0)))
            phase.append("brownout")
        elif t < 48:
            env.append(2.85)
            # hard window: hover at floor with small flicker
            p = POWER_SURGE_PEAK_LOW + 0.04 * ((t % 3) == 0)
            power.append(float(np.clip(p, POWER_SURGE_PEAK_LOW, POWER_SURGE_PEAK_HI)))
            phase.append("SURGE")
        elif t < 62:
            env.append(2.35)
            power.append(float(np.clip(0.40 + 0.12 * np.sin((t - 48) * 0.9), POWER_FLOOR, 0.65)))
            phase.append("aftershock")
        elif t < 78:
            env.append(2.75)
            p = POWER_SURGE_PEAK_LOW + 0.06 if (t % 2 == 0) else POWER_SURGE_PEAK_HI
            power.append(float(p))
            phase.append("SURGE2")
        elif t < 100:
            env.append(1.55)
            power.append(float(min(1.0, 0.48 + 0.024 * (t - 78))))
            phase.append("recover")
        else:
            env.append(1.2)
            power.append(1.0)
            phase.append("settle")
    return env, power, phase


def apply_plan(world: SurgeWorld, plan) -> None:
    if plan.cool_retries:
        mul = 0.62 if plan.storm_active else 0.72
        if world.power < 0.35:
            mul = min(mul, 0.55)
        world.retries = max(0.0, world.retries * mul)
    if plan.quarantine_k > 0:
        world.quarantine_worst(plan.quarantine_k)
    if plan.revive_k > 0 and world.power >= 0.22:
        k = plan.revive_k
        if plan.storm_active and world.power < 0.55:
            k = min(k, 1)
        world.revive(k)
    if plan.concurrency_delta < 0 and world.retries > 0:
        world.retries = max(0.0, world.retries + 0.04 * plan.concurrency_delta)


def run_cycle(
    *,
    cycle: int,
    seed: int,
    paradox: K.Paradox,
    env_sched: list[float],
    power_sched: list[float],
    phases: list[str],
    storm_mode: str = "auto",
    learn: bool = True,
) -> dict:
    world = SurgeWorld(rng=np.random.default_rng(seed + cycle * 17))
    # slightly harder start each cycle (toughen) but not wipe
    hurt = 0.06 + 0.02 * (cycle - 1)
    k_rng = np.random.default_rng(seed + 100 + cycle)
    agents = K.make_swarm(k_rng)
    for a in agents:
        a.coherence = float(np.clip(a.coherence * (1.0 - hurt) + k_rng.uniform(-0.03, 0.02), 0.2, 0.72))

    paradox.install_drivers(agents)
    ambient = 0.0
    stab = 0.88
    prev_env = env_sched[0]
    rows = []
    scars = []
    first_soft = first_hard = None

    for t, (env_I, pwr) in enumerate(zip(env_sched, power_sched)):
        world.power = pwr
        d_env = env_I - prev_env
        thrash_sig = world.retries + (1.0 - world.power) * 1.3
        plan = plan_actions(
            stab,
            success_rate=world.rolling_success(),
            goodput=world.rolling_goodput(),
            env_load=env_I + (1.0 - world.power) * 1.1,
            thrash=thrash_sig,
            storm_mode=storm_mode,  # type: ignore[arg-type]
            d_env=d_env,
            budget_remaining=float(np.clip(world.power, 0, 1)),
            target=TARGET,
        )
        felt = apply_shield(env_I, plan)
        m = world.step(felt)
        apply_plan(world, plan)

        I = from_api(
            world.rolling_goodput(),
            env_I + (1.0 - world.power),
            retries=world.retries,
            budget_remaining=float(np.clip(world.power, 0, 1)),
        )
        for a in agents:
            a.step(I, ambient, k_rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, k_rng)
        paradox.install_drivers(agents)
        stab = K.stability(agents)

        rows.append(
            {
                **m,
                "env_I": env_I,
                "felt_I": felt,
                "stab": stab,
                "storm": plan.storm_active,
                "phase": phases[t],
            }
        )

        # scars for learning
        ph = phases[t]
        if m["rolling_goodput"] < 0.12 and ph in ("SURGE", "SURGE2", "brownout"):
            scars.append({"reason": "tighten_storm", "phase": ph, "gp": m["rolling_goodput"], "power": pwr})
        if m["n_alive"] < 8:
            scars.append({"reason": "tighten_floor", "alive": m["n_alive"], "phase": ph})
        if ph == "recover" and m["rolling_goodput"] > 0.15:
            scars.append({"reason": "climb_recover", "gp": m["rolling_goodput"]})
        if ph == "settle" and m["n_alive"] >= 12:
            scars.append({"reason": "climb_calm", "alive": m["n_alive"]})
        if stab < 0.85 and first_soft is None:
            first_soft = t
            scars.append({"reason": "soft_floor", "stab": stab})
        if (stab < 0.70 or m["n_alive"] < 3) and first_hard is None:
            first_hard = t
            scars.append({"reason": "hard_break_threat", "alive": m["n_alive"]})

        prev_env = env_I

    gp = np.array([r["rolling_goodput"] for r in rows])
    alive = np.array([r["n_alive"] for r in rows], float)
    ph = np.array(phases)
    late_n = max(1, len(rows) // 5)

    def pmean(mask, arr):
        return float(np.mean(arr[mask])) if np.any(mask) else float("nan")

    hard = (ph == "SURGE") | (ph == "SURGE2")
    rec = ph == "recover"
    settle = ph == "settle"

    meta = {
        "final_alive": float(alive[-1]) >= 6,
        "first_soft_break": first_soft,
        "first_hard_break": first_hard if float(np.min(alive)) < 2 else None,
        "recovery_peak": float(np.max(gp[rec])) if np.any(rec) else float(np.max(gp)),
        "recovery_late": pmean(settle, gp),
        "survived_long_hell": float(np.min(alive[hard])) >= 1 if np.any(hard) else True,
        "cycle": cycle,
        "high_I_stab": float(np.mean([r["stab"] for r in rows if r["phase"] in ("SURGE", "SURGE2")])),
    }

    if learn:
        if len(scars) > 90:
            scars = scars[-90:]
        paradox.absorb_episode(scars, episode_meta=meta)
        paradox.compress_scars_to_wisdom(max_intuition_delta=0.08)
        # near-blackout specific investments
        if meta["survived_long_hell"] or meta.get("recovery_late", 0) >= 0.15:
            for k, d in (
                ("countermeasure_invest", 0.04),
                ("damper_bias", 0.03),
                ("viscosity_bias", 0.02),
                ("failure_respect", 0.025),
                ("repair_bias", 0.025),
            ):
                old = float(paradox.intuition.get(k, 1.0))
                paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))
        if meta["first_hard_break"] is not None:
            for k, d in (("damper_bias", 0.03), ("explore_bias", -0.01)):
                old = float(paradox.intuition.get(k, 0.5 if k == "explore_bias" else 1.0))
                if k == "explore_bias":
                    paradox.intuition[k] = float(np.clip(old + d, 0.05, 0.55))
                else:
                    paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))
        # good settle population → reward repair/pairing
        if float(alive[-1]) >= 14:
            for k, d in (("repair_bias", 0.02), ("pairing_strength", 0.02), ("floor_boost", 0.01)):
                if k in paradox.intuition or k == "floor_boost":
                    old = float(paradox.intuition.get(k, 0.1))
                    paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))

    return {
        "cycle": cycle,
        "seed": seed,
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
        "retries_peak": float(np.max([r["retries"] for r in rows])),
        "storm_frac": float(np.mean([1.0 if r["storm"] else 0.0 for r in rows])),
        "stab_late": float(np.mean([r["stab"] for r in rows[-late_n:]])),
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
        "gp_series": gp.tolist(),
        "alive_series": alive.tolist(),
    }


def main() -> int:
    print("=" * 68)
    print(" POWER SURGE LEARN × 3 — train JUST UNDER blackout")
    print(f" power floor during hard windows ≈ {POWER_SURGE_PEAK_LOW:.2f}–{POWER_SURGE_PEAK_HI:.2f} (not 0.04)")
    print(" full blackout skipped on purpose — inch up later")
    print("=" * 68)

    env_sched, power_sched, phases = timeline_near_blackout(140)
    seeds = [7, 13, 21, 42]

    # LEARN arm
    learn_by_c = {1: [], 2: [], 3: []}
    print("\n[LEARN] storm_auto + Paradox scars across 3 cycles")
    for seed in seeds:
        paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
        for c in range(1, N_CYCLES + 1):
            r = run_cycle(
                cycle=c,
                seed=seed,
                paradox=paradox,
                env_sched=env_sched,
                power_sched=power_sched,
                phases=phases,
                storm_mode="auto",
                learn=True,
            )
            learn_by_c[c].append(r)
            print(
                f"  seed={seed} c{c}  "
                f"surge_gp={r['gp_surge']:.3f} alive_s={r['alive_surge']:.1f}  "
                f"rec_gp={r['gp_recover']:.3f}  end_alive={r['alive_end']:.0f}  "
                f"settle_gp={r['gp_settle']:.3f}  "
                f"cm={r['intuition'].get('countermeasure_invest', 0):.2f} "
                f"damp={r['intuition'].get('damper_bias', 0):.2f}"
            )

    # FROZEN control (reset DNA each cycle)
    frozen_by_c = {1: [], 2: [], 3: []}
    print("\n[FROZEN] storm_auto, Paradox reset each cycle (no carry)")
    for seed in seeds:
        for c in range(1, N_CYCLES + 1):
            paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
            r = run_cycle(
                cycle=c,
                seed=seed + 50,
                paradox=paradox,
                env_sched=env_sched,
                power_sched=power_sched,
                phases=phases,
                storm_mode="auto",
                learn=False,
            )
            frozen_by_c[c].append(r)
        print(
            f"  seed={seed} frozen c1→c3 end_alive "
            f"{frozen_by_c[1][-1]['alive_end']:.0f} → {frozen_by_c[3][-1]['alive_end']:.0f}  "
            f"surge_gp {frozen_by_c[1][-1]['gp_surge']:.3f} → {frozen_by_c[3][-1]['gp_surge']:.3f}"
        )

    def summ(by_c, c, key):
        return float(np.mean([x[key] for x in by_c[c]]))

    print("\n[LEARN SUMMARY]")
    print(f"  {'metric':20s}  c1      c2      c3     Δc3−c1")
    for key in (
        "gp_surge",
        "alive_surge",
        "alive_min_surge",
        "gp_recover",
        "alive_recover",
        "gp_settle",
        "alive_end",
        "gp_late",
        "stab_late",
    ):
        a, b, c = summ(learn_by_c, 1, key), summ(learn_by_c, 2, key), summ(learn_by_c, 3, key)
        print(f"  {key:20s}  {a:6.3f}  {b:6.3f}  {c:6.3f}  {c-a:+.3f}")

    print("\n[FROZEN SUMMARY] (noise floor — should be ~flat)")
    for key in ("gp_surge", "alive_end", "gp_settle"):
        a, c = summ(frozen_by_c, 1, key), summ(frozen_by_c, 3, key)
        print(f"  {key:20s}  c1={a:.3f}  c3={c:.3f}  Δ={c-a:+.3f}")

    d_surge = summ(learn_by_c, 3, "gp_surge") - summ(learn_by_c, 1, "gp_surge")
    d_alive = summ(learn_by_c, 3, "alive_end") - summ(learn_by_c, 1, "alive_end")
    d_settle = summ(learn_by_c, 3, "gp_settle") - summ(learn_by_c, 1, "gp_settle")
    d_fr_alive = summ(frozen_by_c, 3, "alive_end") - summ(frozen_by_c, 1, "alive_end")

    print("\n[TRANSFER vs FROZEN]")
    print(f"  learn Δ end_alive c3−c1:  {d_alive:+.2f}")
    print(f"  frozen Δ end_alive c3−c1: {d_fr_alive:+.2f}")
    print(f"  learn Δ surge_gp:         {d_surge:+.3f}")
    print(f"  learn Δ settle_gp:        {d_settle:+.3f}")

    if d_alive > 1.5 and d_alive > d_fr_alive + 1.0:
        verdict = (
            "LEARNING_SHOWS: under near-blackout floor, 3 cycles improve end survival "
            "beyond frozen noise. Keep training here before inching power floor down."
        )
    elif d_surge > 0.02 or d_settle > 0.02:
        verdict = (
            "LEARNING_PARTIAL: goodput under surge/settle inches up; survival mixed. "
            "Shell + scars both matter — continue at this floor."
        )
    elif d_alive > 0.5:
        verdict = "LEARNING_SMALL: slight survival drift — more cycles or scar weight before lowering floor."
    else:
        verdict = (
            "LEARNING_FLAT: at this floor shell already carries load; scars don't move much. "
            "Try longer cycles or harsher brownout before lowering power floor."
        )
    print(f"\n  VERDICT → {verdict}")

    # plot learn c1 vs c3 (seed 13)
    paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
    r1 = run_cycle(cycle=1, seed=13, paradox=paradox, env_sched=env_sched, power_sched=power_sched, phases=phases, learn=True)
    r2 = run_cycle(cycle=2, seed=13, paradox=paradox, env_sched=env_sched, power_sched=power_sched, phases=phases, learn=True)
    r3 = run_cycle(cycle=3, seed=13, paradox=paradox, env_sched=env_sched, power_sched=power_sched, phases=phases, learn=True)

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    x = np.arange(len(env_sched))
    ax = axes[0]
    ax.plot(x, power_sched, color="#f39c12", label="power (floor~0.2)", lw=1.5)
    ax.axhline(POWER_FLOOR, color="#e74c3c", ls="--", lw=1, label="train floor")
    ax.axhline(0.04, color="#555", ls=":", lw=1, label="old blackout (~0.04)")
    ax.plot(x, env_sched, color="#9b59b6", alpha=0.7, label="env I")
    ax.axvspan(28, 48, color="#c0392b", alpha=0.12)
    ax.axvspan(62, 78, color="#922b21", alpha=0.12)
    ax.set_ylabel("power / I")
    ax.set_title("Near-blackout train floor · learn c1 vs c3")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(x, r1["gp_series"], color="#888", label="c1 goodput", lw=1.2)
    ax2.plot(x, r3["gp_series"], color="#2ecc71", label="c3 goodput", lw=1.5)
    ax2.set_ylabel("goodput")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)
    ax2.set_ylim(0, 1.05)

    ax3 = axes[2]
    ax3.plot(x, np.array(r1["alive_series"]) / 32, color="#888", label="c1 alive")
    ax3.plot(x, np.array(r3["alive_series"]) / 32, color="#40d0ff", label="c3 alive", lw=1.5)
    ax3.set_ylabel("alive frac")
    ax3.set_xlabel("step")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)
    ax3.set_ylim(0, 1.05)
    fig.tight_layout()
    png = OUT / "hard_power_surge_learn.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # cycle bars
    fig2, ax = plt.subplots(figsize=(9, 5))
    metrics = ["gp_surge", "alive_surge", "gp_settle", "alive_end"]
    labels = ["surge gp", "surge alive", "settle gp", "end alive"]
    x = np.arange(len(metrics))
    w = 0.25
    for i, c in enumerate((1, 2, 3)):
        ys = [summ(learn_by_c, c, m) for m in metrics]
        # scale alive metrics for shared axis roughly
        ys_plot = []
        for m, y in zip(metrics, ys):
            ys_plot.append(y / 32.0 if "alive" in m else y)
        ax.bar(x + (i - 1) * w, ys_plot, w, label=f"c{c}")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("goodput or alive frac")
    ax.set_title("Learn across 3 near-blackout surge cycles")
    ax.legend()
    ax.grid(True, alpha=0.25, axis="y")
    fig2.tight_layout()
    png2 = OUT / "hard_power_surge_learn_bars.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "hard_power_surge_learn_v1",
        "power_floor_train": POWER_FLOOR,
        "surge_power_band": [POWER_SURGE_PEAK_LOW, POWER_SURGE_PEAK_HI],
        "note": "Full blackout (~0.04) skipped; train just under threshold",
        "n_cycles": N_CYCLES,
        "seeds": seeds,
        "learn": {
            c: {k: summ(learn_by_c, c, k) for k in (
                "gp_surge", "alive_surge", "alive_min_surge", "gp_recover",
                "alive_recover", "gp_settle", "alive_end", "gp_late", "stab_late",
            )}
            for c in (1, 2, 3)
        },
        "frozen": {
            c: {k: summ(frozen_by_c, c, k) for k in ("gp_surge", "alive_end", "gp_settle")}
            for c in (1, 2, 3)
        },
        "delta_learn_c3_c1": {
            "gp_surge": d_surge,
            "alive_end": d_alive,
            "gp_settle": d_settle,
        },
        "delta_frozen_alive_end": d_fr_alive,
        "final_intuition_sample": learn_by_c[3][0]["intuition"],
        "verdict": verdict,
    }
    js = OUT / "hard_power_surge_learn_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
