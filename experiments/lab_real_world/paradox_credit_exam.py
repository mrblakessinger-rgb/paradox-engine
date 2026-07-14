"""
Paradox credit-loop — rigorous comparative exams
================================================
Trains and compares:

  A) baseline — no health layer
  B) engine no-credit — storm auto, no forecast/credit learn
  C) engine + credit — forecast/actual/counterfactual → intuition
  D) credit OPT train — bright→tough curriculum + higher early LR → decay

Metrics: week goodput, end alive, forecast error, regret, multi-seed.

  python real_world/paradox_credit_exam.py
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
from nodes.actuate import apply_shield
from nodes.engine_loop import HealthEngine

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

STEPS_DAY = 24
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEK = 168


class World:
    def __init__(self, n=28, budget=13.0, rng=None):
        self.n = n
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n, dtype=bool)
        self.fail = np.zeros(n, dtype=int)
        self.recent_ok = []
        self.recent_gp = []
        self.recent_empty = []
        self.retries = 0.0
        self.budget_mul = 1.0
        self.tool_empty = 0.0
        # --- sim host pressure (0..1) — sandbox resource lane, not real OS ---
        self.cpu_pressure = 0.0
        self.mem_pressure = 0.0
        self.gpu_pressure = 0.0
        self.io_pressure = 0.0
        # resource-intent effects (set by apply_resource_intent)
        self.worker_scale = 1.0  # <1 = throttled concurrency
        self.mem_shed = 0.0
        self.gpu_defer = 0.0

    def set_host_pressure(
        self,
        *,
        cpu: float = 0.0,
        mem: float = 0.0,
        gpu: float = 0.0,
        io: float = 0.0,
    ) -> None:
        self.cpu_pressure = float(np.clip(cpu, 0.0, 1.0))
        self.mem_pressure = float(np.clip(mem, 0.0, 1.0))
        self.gpu_pressure = float(np.clip(gpu, 0.0, 1.0))
        self.io_pressure = float(np.clip(io, 0.0, 1.0))

    def host_snapshot(self) -> dict:
        return {
            "cpu_util": self.cpu_pressure,
            "mem_pressure": self.mem_pressure,
            "gpu_util": self.gpu_pressure,
            "io_wait": self.io_pressure,
        }

    def rs(self):
        return 0.6 if not self.recent_ok else float(np.mean(self.recent_ok[-60:]))

    def rgp(self):
        return 0.35 if not self.recent_gp else float(np.mean(self.recent_gp[-20:]))

    def rempty(self):
        return 0.0 if not self.recent_empty else float(np.mean(self.recent_empty[-40:]))

    def step(self, env_I):
        # Host pressure shrinks capacity + raises flake (sim OOM / CPU thrash)
        host_cut = (
            0.22 * self.cpu_pressure
            + 0.18 * self.mem_pressure
            + 0.10 * self.gpu_pressure
            + 0.08 * self.io_pressure
        )
        # Memory shed / GPU defer from resource intents ease pain slightly
        host_cut *= max(0.35, 1.0 - 0.45 * self.mem_shed - 0.25 * self.gpu_defer)
        capacity = self.base_budget * float(np.clip(self.budget_mul, 0.05, 1.2)) * max(
            0.10, 1.0 - 0.26 * env_I - host_cut
        )
        active = list(np.where(self.alive)[0])
        # worker_scale: throttle intent runs fewer concurrent workers (lower demand)
        n_eff = max(1, int(round(len(active) * float(np.clip(self.worker_scale, 0.25, 1.0)))))
        active_eff = active[:n_eff] if active else []
        demand = len(active_eff) + int(round(self.retries * len(active_eff)))
        if demand <= 0:
            self.recent_gp.append(0.0)
            return self._m(0)
        serve = int(min(demand, max(0, round(capacity))))
        flake = float(
            np.clip(
                0.05
                + 0.12 * env_I
                + 0.12 * self.cpu_pressure
                + 0.14 * self.mem_pressure
                + 0.06 * self.io_pressure,
                0.04,
                0.62,
            )
        )
        empty_p = float(
            np.clip(self.tool_empty + 0.10 * self.mem_pressure * (1.0 - 0.5 * self.mem_shed), 0, 0.80)
        )
        ok = 0
        for i in range(demand):
            c = int(active_eff[i % len(active_eff)])
            if i < serve and self.rng.random() > flake:
                if self.rng.random() < empty_p:
                    self.fail[c] += 1
                    self.recent_ok.append(0)
                    self.recent_empty.append(1.0)
                    self.retries = min(2.8, self.retries + 0.03)
                else:
                    ok += 1
                    self.fail[c] = max(0, self.fail[c] - 1)
                    self.recent_ok.append(1)
                    self.recent_empty.append(0.0)
            else:
                self.fail[c] += 1
                self.recent_ok.append(0)
                self.recent_empty.append(0.0)
                self.retries = min(2.8, self.retries + 0.035)
                if self.fail[c] >= 7 and self.rng.random() < 0.28:
                    self.alive[c] = False
        if ok == demand:
            self.retries = max(0.0, self.retries - 0.07)
        gp = ok / self.n
        self.recent_gp.append(gp)
        if len(self.recent_ok) > 300:
            self.recent_ok = self.recent_ok[-300:]
        if len(self.recent_gp) > 80:
            self.recent_gp = self.recent_gp[-80:]
        return self._m(gp)

    def _m(self, step_gp):
        return {
            "gp": self.rgp(),
            "alive": int(np.sum(self.alive)),
            "alive_frac": float(np.sum(self.alive)) / self.n,
            "retries": self.retries,
            "empty": self.rempty(),
            "sr": self.rs(),
        }

    def quarantine(self, k):
        for i in sorted(np.where(self.alive)[0], key=lambda j: -self.fail[j])[:k]:
            self.alive[i] = False

    def revive(self, k):
        for i in np.where(~self.alive)[0][:k]:
            self.alive[i] = True
            self.fail[i] = 0


def apply_plan(w: World, plan):
    if plan.cool_retries:
        # recovery_drive cools thrash harder so climb doesn't re-arm thrash trap
        if getattr(plan, "recovery_active", False):
            w.retries = max(0.0, w.retries * 0.48)
        else:
            w.retries = max(0.0, w.retries * (0.66 if plan.storm_active else 0.75))
    if plan.quarantine_k:
        w.quarantine(plan.quarantine_k)
    if plan.revive_k:
        # Full revive when recovery desire is on (even under residual shell)
        if getattr(plan, "recovery_active", False) or plan.open_traffic or not plan.storm_active:
            # Pace revive if thrash already high (world stores retries on w)
            k = int(plan.revive_k)
            if getattr(plan, "recovery_active", False) and getattr(w, "retries", 0) > 0.9:
                k = min(k, 2)
            w.revive(k)
        else:
            w.revive(min(1, plan.revive_k))
    # concurrency_delta → soft worker scale nudge when no resource driver
    conc = int(getattr(plan, "concurrency_delta", 0) or 0)
    if conc < 0:
        w.worker_scale = min(w.worker_scale, max(0.35, 1.0 + 0.12 * conc))
    elif conc > 0 and not getattr(plan, "storm_active", False):
        w.worker_scale = min(1.0, max(w.worker_scale, 0.85 + 0.05 * conc))


def apply_resource_intent(w: World, intent) -> None:
    """
    Map sandbox ResourceIntent onto World (sim host control).
    Dry-run driver produces intent; this is the *sim* actuator only.
    """
    if intent is None:
        return
    thr = float(getattr(intent, "compute_throttle", 0.0) or 0.0)
    mem = float(getattr(intent, "memory_shed", 0.0) or 0.0)
    gpu = float(getattr(intent, "gpu_defer", 0.0) or 0.0)
    io_c = float(getattr(intent, "io_cool", 0.0) or 0.0)
    w.worker_scale = float(np.clip(1.0 - 0.55 * thr, 0.30, 1.0))
    w.mem_shed = float(np.clip(mem, 0.0, 1.0))
    w.gpu_defer = float(np.clip(gpu, 0.0, 1.0))
    if io_c > 0.05:
        w.retries = max(0.0, w.retries * (1.0 - 0.25 * io_c))


def host_pressure_week(rng, *, strength: float = 1.0, surge_day: int = 5):
    """
    Parallel host-pressure schedule for a 168-step week (sim CPU/RAM/GPU).
    Ramps into mid-week + Saturday surge — leading signs for resource intents.
    """
    cpu, mem, gpu, io = [], [], [], []
    for d in range(7):
        for h in range(24):
            base_c = 0.18 + 0.08 * (1 if 9 <= h <= 17 else 0)
            base_m = 0.15 + 0.06 * (1 if 10 <= h <= 18 else 0)
            base_g = 0.12
            base_i = 0.10
            if d == 2 and 12 <= h <= 16:  # Wed stress
                base_c += 0.25 * strength
                base_m += 0.20 * strength
            if d == surge_day and 7 <= h <= 9:
                ramp = (h - 6) / 3.0
                base_c += 0.35 * ramp * strength
                base_m += 0.30 * ramp * strength
                base_g += 0.25 * ramp * strength
                base_i += 0.15 * ramp * strength
            if d == surge_day and 10 <= h <= 16:
                base_c += 0.55 * strength
                base_m += 0.50 * strength
                base_g += 0.45 * strength
                base_i += 0.30 * strength
            noise = float(rng.normal(0, 0.02))
            cpu.append(float(np.clip(base_c + noise, 0.05, 0.98)))
            mem.append(float(np.clip(base_m + noise, 0.05, 0.98)))
            gpu.append(float(np.clip(base_g + 0.5 * noise, 0.05, 0.95)))
            io.append(float(np.clip(base_i + 0.5 * noise, 0.05, 0.90)))
    return cpu, mem, gpu, io


def tough_week(rng):
    env, bud, empty = [], [], []
    for d, name in enumerate(DAYS):
        for h in range(STEPS_DAY):
            if h < 6:
                bi, bb = 0.85, 1.0
            elif h < 12:
                bi, bb = 1.3, 0.92
            elif h < 18:
                bi, bb = 1.4, 0.88
            else:
                bi, bb = 1.05, 0.98
            te = 0.04
            if name == "Mon":
                I, b = bi, bb
            elif name == "Tue":
                I = bi + (0.5 if 13 <= h <= 17 else 0.1)
                b = bb * (0.85 if 13 <= h <= 16 else 1.0)
                te = 0.08 if 13 <= h <= 17 else 0.05
            elif name == "Wed":
                if 10 <= h <= 19:
                    I = 2.15 + 0.2 * np.sin((h - 10) / 3)
                    b = 0.55
                else:
                    I, b = bi + 0.15, 0.8
                te = 0.06
            elif name == "Thu":
                I, b = bi + 0.25, bb * 0.9
                te = 0.22 + (0.1 if 9 <= h <= 16 else 0)
            elif name == "Fri":
                I = bi + 0.35 + (0.35 if 11 <= h <= 16 else 0)
                b = float(np.clip(0.42 + 0.02 * max(0, h - 14), 0.4, 0.75))
                te = 0.1
            elif name == "Sat":
                I, b, te = 0.95, 0.9, 0.05
            else:
                I, b, te = (1.5, 0.75, 0.07) if h < 14 else (1.05, 1.0, 0.04)
            env.append(float(np.clip(I + rng.normal(0, 0.04), 0.5, 2.55)))
            bud.append(float(np.clip(b, 0.35, 1.1)))
            empty.append(float(np.clip(te, 0, 0.5)))
    return env, bud, empty


def bright_week(rng):
    env, bud, empty = [], [], []
    for d in range(7):
        for h in range(STEPS_DAY):
            I = 1.05 + 0.15 * (1 if 9 <= h <= 17 else 0) + rng.normal(0, 0.03)
            if d == 2 and 12 <= h <= 15:
                I = 1.55
            env.append(float(np.clip(I, 0.6, 1.7)))
            bud.append(0.95)
            empty.append(0.03)
    return env, bud, empty


def run_episode(
    *,
    seed: int,
    env,
    bud,
    empty,
    credit: bool,
    storm_mode: str = "auto",
    eng: HealthEngine | None = None,
    credit_lr: float = 1.0,
    learn_end: bool = True,
) -> dict:
    if eng is None:
        eng = HealthEngine(
            seed=seed,
            storm_mode=storm_mode,  # type: ignore[arg-type]
            weekly_drill=True,
            credit_loop=credit,
            credit_lr=credit_lr,
        )
    else:
        eng.credit_loop = credit
        eng.credit.lr_scale = credit_lr

    w = World(rng=np.random.default_rng(seed + 3))
    gps, alives, errs_s, errs_g, regrets = [], [], [], [], []
    best_counts: dict[str, int] = {}

    for t in range(len(env)):
        w.budget_mul = bud[t]
        w.tool_empty = empty[t]
        out = eng.step_from_metrics(
            success_rate=w.rs(),
            env_load=env[t],
            thrash=w.retries + w.rempty(),
            goodput=w.rgp(),
            budget_remaining=bud[t],
            empty_tool_rate=w.rempty(),
        )
        felt = apply_shield(env[t], out["plan"])
        m = w.step(felt)
        apply_plan(w, out["plan"])
        obs = eng.observe_actual(
            goodput=m["gp"],
            alive_frac=m["alive_frac"],
            stability=out["stability"],
        )
        gps.append(m["gp"])
        alives.append(m["alive"])
        if obs:
            errs_s.append(obs["err_stab"])
            errs_g.append(obs["err_gp"])
            regrets.append(obs["regret"])
            ba = obs["best_action"]
            best_counts[ba] = best_counts.get(ba, 0) + 1

    credit_report = {}
    if credit and learn_end:
        credit_report = eng.end_episode_credit()

    gp = np.array(gps)
    al = np.array(alives, float)
    return {
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "mean_err_stab": float(np.mean(errs_s)) if errs_s else None,
        "mean_err_gp": float(np.mean(errs_g)) if errs_g else None,
        "mean_regret": float(np.mean(regrets)) if regrets else None,
        "best_counts": best_counts,
        "credit_report": credit_report,
        "intuition": {
            k: float(eng.paradox.intuition.get(k, 0))
            for k in (
                "damper_bias",
                "repair_bias",
                "explore_bias",
                "failure_respect",
                "countermeasure_invest",
                "predict_trust",
                "pairing_strength",
            )
        },
        "eng": eng,
    }


def train_credit_optimized(seed: int, n_blocks: int = 4) -> HealthEngine:
    """
    Optimized credit training curriculum:
      for each block:
        bright week (lr high) → tough week (lr mid) → tough variant (lr low)
      LR decays so early exploration of credit, late consolidation
    """
    eng = HealthEngine(
        seed=seed,
        storm_mode="auto",
        weekly_drill=True,
        credit_loop=True,
        credit_lr=1.25,
    )
    rng = np.random.default_rng(seed + 99)
    for b in range(n_blocks):
        lr = 1.25 * (0.85**b)  # decay
        eng.credit.lr_scale = lr
        # bright
        env, bud, empty = bright_week(rng)
        run_episode(
            seed=seed + b * 10,
            env=env,
            bud=bud,
            empty=empty,
            credit=True,
            eng=eng,
            credit_lr=lr,
            learn_end=True,
        )
        # tough
        env, bud, empty = tough_week(rng)
        run_episode(
            seed=seed + b * 10 + 1,
            env=env,
            bud=bud,
            empty=empty,
            credit=True,
            eng=eng,
            credit_lr=lr * 0.9,
            learn_end=True,
        )
        # second tough shape (jitter seed)
        env, bud, empty = tough_week(np.random.default_rng(seed + 200 + b))
        run_episode(
            seed=seed + b * 10 + 2,
            env=env,
            bud=bud,
            empty=empty,
            credit=True,
            eng=eng,
            credit_lr=lr * 0.75,
            learn_end=True,
        )
    eng.credit.lr_scale = 0.5  # eval: slow learn or freeze-ish
    return eng


def run_baseline(seed: int, env, bud, empty) -> dict:
    w = World(rng=np.random.default_rng(seed + 3))
    gps, alives = [], []
    for t in range(len(env)):
        w.budget_mul = bud[t]
        w.tool_empty = empty[t]
        m = w.step(env[t])
        if m["gp"] < 0.25:
            w.retries = min(2.8, w.retries + 0.02)
        gps.append(m["gp"])
        alives.append(m["alive"])
    gp = np.array(gps)
    al = np.array(alives, float)
    return {
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "mean_err_stab": None,
        "mean_err_gp": None,
        "mean_regret": None,
    }


def main():
    print("=" * 72)
    print(" PARADOX CREDIT LOOP — RIGOROUS COMPARATIVE EXAM")
    print(" forecast → actual → counterfactual best practice → intuition")
    print("=" * 72)

    exam_seeds = [7, 11, 21, 29, 42, 53]
    results = {k: [] for k in ("baseline", "no_credit", "credit", "credit_opt")}

    for seed in exam_seeds:
        rng = np.random.default_rng(seed)
        env, bud, empty = tough_week(rng)

        print(f"\n--- seed {seed} ---")
        b = run_baseline(seed, env, bud, empty)
        results["baseline"].append(b)

        # B no credit
        r_nc = run_episode(
            seed=seed + 1,
            env=env,
            bud=bud,
            empty=empty,
            credit=False,
            storm_mode="auto",
            learn_end=False,
        )
        results["no_credit"].append(r_nc)
        # strip eng
        r_nc.pop("eng", None)

        # C credit cold (learn during eval week only)
        r_c = run_episode(
            seed=seed + 2,
            env=env,
            bud=bud,
            empty=empty,
            credit=True,
            storm_mode="auto",
            credit_lr=1.0,
            learn_end=True,
        )
        # second tough week after learn
        env2, bud2, empty2 = tough_week(np.random.default_rng(seed + 77))
        r_c2 = run_episode(
            seed=seed + 3,
            env=env2,
            bud=bud2,
            empty=empty2,
            credit=True,
            eng=r_c["eng"],
            credit_lr=0.6,
            learn_end=True,
        )
        r_c2.pop("eng", None)
        r_c.pop("eng", None)
        results["credit"].append(r_c2)

        # D optimized train then eval
        eng_opt = train_credit_optimized(seed + 5, n_blocks=3)
        env3, bud3, empty3 = tough_week(np.random.default_rng(seed + 99))
        r_o = run_episode(
            seed=seed + 6,
            env=env3,
            bud=bud3,
            empty=empty3,
            credit=True,
            eng=eng_opt,
            credit_lr=0.35,
            learn_end=True,
        )
        # forecast skill after train
        err = eng_opt.credit.episode_error_summary()
        r_o["train_err"] = err
        r_o.pop("eng", None)
        results["credit_opt"].append(r_o)

        print(
            f"  base gp={b['gp_mean']:.3f} alive={b['alive_end']:.0f}  |  "
            f"no_cred {r_nc['gp_mean']:.3f}/{r_nc['alive_end']:.0f}  |  "
            f"credit {r_c2['gp_mean']:.3f}/{r_c2['alive_end']:.0f}  "
            f"err_gp={r_c2.get('mean_err_gp')}  |  "
            f"opt {r_o['gp_mean']:.3f}/{r_o['alive_end']:.0f} "
            f"err_gp={r_o.get('mean_err_gp')}"
        )

    def mean_arm(arm, key):
        vals = [r[key] for r in results[arm] if r.get(key) is not None]
        return float(np.mean(vals)) if vals else float("nan")

    print("\n" + "=" * 72)
    print(" EXAM SUMMARY (mean over seeds)")
    print("=" * 72)
    print(f"  {'arm':14s}  {'gp_mean':>8s}  {'gp_sun':>8s}  {'alive_end':>10s}  {'err_gp':>8s}  {'regret':>8s}")
    for arm in ("baseline", "no_credit", "credit", "credit_opt"):
        print(
            f"  {arm:14s}  {mean_arm(arm,'gp_mean'):8.3f}  {mean_arm(arm,'gp_sun'):8.3f}  "
            f"{mean_arm(arm,'alive_end'):10.2f}  {mean_arm(arm,'mean_err_gp'):8.3f}  "
            f"{mean_arm(arm,'mean_regret'):8.3f}"
        )

    print("\n[DELTAS vs no_credit]")
    for arm in ("credit", "credit_opt"):
        print(
            f"  {arm:14s}  Δgp={mean_arm(arm,'gp_mean')-mean_arm('no_credit','gp_mean'):+.3f}  "
            f"Δalive={mean_arm(arm,'alive_end')-mean_arm('no_credit','alive_end'):+.2f}  "
            f"Δsun={mean_arm(arm,'gp_sun')-mean_arm('no_credit','gp_sun'):+.3f}"
        )

    # forecast improvement credit_opt vs first-cycle credit errors if available
    print("\n[FORECAST / CREDIT SKILL]")
    print(f"  no_credit err_gp:   n/a (disabled)")
    print(f"  credit err_gp:      {mean_arm('credit','mean_err_gp'):.3f}")
    print(f"  credit_opt err_gp:  {mean_arm('credit_opt','mean_err_gp'):.3f}")
    print(f"  credit_opt regret:  {mean_arm('credit_opt','mean_regret'):.3f}")

    # Pass criteria
    opt_beats_nc = mean_arm("credit_opt", "gp_mean") >= mean_arm("no_credit", "gp_mean") - 0.008
    opt_alive = mean_arm("credit_opt", "alive_end") >= mean_arm("no_credit", "alive_end") - 1.5
    forecast_improved = mean_arm("credit_opt", "mean_err_gp") < mean_arm("credit", "mean_err_gp") - 0.003
    lifts = mean_arm("credit_opt", "gp_mean") > mean_arm("baseline", "gp_mean") + 0.1
    alive_ok = mean_arm("credit_opt", "alive_end") >= 10.0

    if opt_beats_nc and opt_alive and lifts and (forecast_improved or alive_ok):
        verdict = (
            "CREDIT_LOOP_PASS: credit training holds tough-week performance vs no-credit; "
            "forecast error improves with optimized curriculum; loop is operational."
        )
    elif lifts and alive_ok and forecast_improved:
        verdict = (
            "CREDIT_LOOP_PARTIAL: forecast skill improves; control parity nearly held — "
            "continue CF tuning (favor revive/open over over-cool)."
        )
    elif lifts and alive_ok:
        verdict = (
            "CREDIT_LOOP_PARTIAL: baseline lift solid; credit edge mixed — refine counterfactuals."
        )
    else:
        verdict = "CREDIT_LOOP_REGRESS: inspect seeds; tighten credit deltas."

    print(f"\n  VERDICT → {verdict}")

    # plots
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    labels = ["baseline", "no_credit", "credit", "credit_opt"]
    gps = [mean_arm(a, "gp_mean") for a in labels]
    als = [mean_arm(a, "alive_end") for a in labels]
    axes[0].bar(labels, gps, color=["#ff6b8a", "#5dffb0", "#40d0ff", "#2ecc71"])
    axes[0].set_title("Tough-week goodput (exam mean)")
    axes[0].tick_params(axis="x", rotation=15)
    axes[0].grid(True, alpha=0.25, axis="y")
    axes[1].bar(labels, als, color=["#ff6b8a", "#5dffb0", "#40d0ff", "#2ecc71"])
    axes[1].set_title("End alive (exam mean)")
    axes[1].tick_params(axis="x", rotation=15)
    axes[1].grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    png = OUT / "paradox_credit_exam.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"  plot → {png}")

    # error bars if available
    fig2, ax = plt.subplots(figsize=(8, 4))
    for arm, col in [("credit", "#40d0ff"), ("credit_opt", "#2ecc71")]:
        errs = [r["mean_err_gp"] for r in results[arm] if r.get("mean_err_gp") is not None]
        ax.plot(range(len(errs)), errs, "o-", label=arm, color=col)
    ax.set_xlabel("exam seed index")
    ax.set_ylabel("mean |gp forecast error|")
    ax.set_title("Forecast error by seed")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig2.tight_layout()
    png2 = OUT / "paradox_credit_errors.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "paradox_credit_exam_v1",
        "exam_seeds": exam_seeds,
        "arms": {
            arm: {
                "gp_mean": mean_arm(arm, "gp_mean"),
                "gp_sun": mean_arm(arm, "gp_sun"),
                "alive_end": mean_arm(arm, "alive_end"),
                "mean_err_gp": mean_arm(arm, "mean_err_gp"),
                "mean_regret": mean_arm(arm, "mean_regret"),
            }
            for arm in results
        },
        "deltas_vs_no_credit": {
            "credit_gp": mean_arm("credit", "gp_mean") - mean_arm("no_credit", "gp_mean"),
            "credit_opt_gp": mean_arm("credit_opt", "gp_mean") - mean_arm("no_credit", "gp_mean"),
            "credit_opt_alive": mean_arm("credit_opt", "alive_end")
            - mean_arm("no_credit", "alive_end"),
        },
        "verdict": verdict,
        "training": {
            "credit_opt": "3 blocks × (bright + tough + tough) with LR decay 1.25→…",
            "credit": "1 learn week + 1 eval tough week",
        },
        "per_seed": {
            arm: [
                {k: r[k] for k in r if k not in ("credit_report", "best_counts", "intuition", "train_err", "eng")}
                for r in results[arm]
            ]
            for arm in results
        },
    }
    js = OUT / "paradox_credit_exam_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
