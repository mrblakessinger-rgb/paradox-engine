"""
Credit exams @ target 0.935 + surprise surge in the calm
========================================================
- Desire coherence 0.935
- 3 learning runs (carry engines, refine between)
- During each exam tough-week, inject a SURPRISE surge on Saturday calm
  (relaxing moment → sudden thrash) to watch storm/damper/beacon response

  python real_world/paradox_credit_exam_0935_surge.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.actuate import apply_shield
from nodes.engine_loop import HealthEngine
from paradox_credit_exam import World, apply_plan, bright_week, tough_week, STEPS_DAY, DAYS

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = 0.935
N_RUNS = 3
EXAM_SEEDS = [7, 11, 21, 29, 42, 53]
# Saturday = day index 5, hours 10-16 → surprise surge in the "relaxing" part of the week
SURGE_DAY = 5
SURGE_HOURS = range(10, 17)


def inject_surprise_surge(env, bud, empty):
    """Copy schedules; spike Saturday mid-day (was quiet)."""
    env, bud, empty = list(env), list(bud), list(empty)
    flags = [False] * len(env)
    for d in range(7):
        for h in range(STEPS_DAY):
            t = d * STEPS_DAY + h
            if d == SURGE_DAY and h in SURGE_HOURS:
                env[t] = 2.45
                bud[t] = 0.42
                empty[t] = 0.14
                flags[t] = True
    return env, bud, empty, flags


def run_episode(seed, env, bud, empty, eng, credit_lr=1.0, learn_end=True, surge_flags=None):
    eng.credit.lr_scale = credit_lr
    eng.credit_loop = True
    eng.target = TARGET
    eng.paradox.intuition["target_coherence"] = TARGET
    w = World(rng=np.random.default_rng(seed + 3))
    gps, alives, stabs = [], [], []
    errs_g, regrets = [], []
    storm_on_surge, storm_on_calm = [], []
    damper_on_surge, damper_calm = [], []
    beacon_on_surge = []

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
            goodput=m["gp"], alive_frac=m["alive_frac"], stability=out["stability"]
        )
        gps.append(m["gp"])
        alives.append(m["alive"])
        stabs.append(out["stability"])
        if surge_flags and surge_flags[t]:
            storm_on_surge.append(1.0 if out["storm_active"] else 0.0)
            damper_on_surge.append(out["damper_live"])
            beacon_on_surge.append(1.0 if out["beacon_active"] else 0.0)
        elif surge_flags and not surge_flags[t] and (t % STEPS_DAY) >= 10:
            # sample non-surge daytime for comparison
            if not out.get("weekly_drill"):
                storm_on_calm.append(1.0 if out["storm_active"] else 0.0)
                damper_calm.append(out["damper_live"])
        if obs:
            errs_g.append(obs["err_gp"])
            regrets.append(obs["regret"])

    if learn_end:
        eng.end_episode_credit()

    gp, al, st = np.array(gps), np.array(alives, float), np.array(stabs)
    # surge window metrics
    if surge_flags:
        idx = [i for i, f in enumerate(surge_flags) if f]
        gp_surge = float(np.mean(gp[idx])) if idx else None
        alive_surge = float(np.mean(al[idx])) if idx else None
    else:
        gp_surge = alive_surge = None

    return {
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "stab_late": float(np.mean(st[-STEPS_DAY:])),
        "stab_vs_target": float(np.mean(st[-STEPS_DAY:]) - TARGET),
        "mean_err_gp": float(np.mean(errs_g)) if errs_g else None,
        "mean_regret": float(np.mean(regrets)) if regrets else None,
        "gp_during_surprise": gp_surge,
        "alive_during_surprise": alive_surge,
        "storm_frac_during_surprise": float(np.mean(storm_on_surge)) if storm_on_surge else 0.0,
        "beacon_frac_during_surprise": float(np.mean(beacon_on_surge)) if beacon_on_surge else 0.0,
        "damper_during_surprise": float(np.mean(damper_on_surge)) if damper_on_surge else None,
        "damper_relax_sample": float(np.mean(damper_calm)) if damper_calm else None,
        "storm_frac_relax_sample": float(np.mean(storm_on_calm)) if storm_on_calm else 0.0,
        "intuition": {
            k: float(eng.paradox.intuition.get(k, 0))
            for k in (
                "damper_bias",
                "repair_bias",
                "explore_bias",
                "countermeasure_invest",
                "pairing_strength",
                "target_coherence",
            )
        },
        "gp_series": gp.tolist(),
        "storm_series": None,  # filled optionally
    }


def run_baseline(seed, env, bud, empty):
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
    gp, al = np.array(gps), np.array(alives, float)
    return {
        "gp_mean": float(np.mean(gp)),
        "alive_end": float(al[-1]),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
    }


def train_block(eng, seed, lr, rng):
    eng.credit.lr_scale = lr
    for i, fn in enumerate((bright_week, tough_week, tough_week)):
        r = rng if i < 2 else np.random.default_rng(int(rng.integers(1e9)))
        env, bud, empty = fn(r)
        # bright: no surprise; tough: inject Saturday surge so credit learns it
        if i == 0:
            flags = None
        else:
            env, bud, empty, flags = inject_surprise_surge(env, bud, empty)
        run_episode_simple(eng, seed + i, env, bud, empty, lr * (0.85 if i else 1.0), flags)


def run_episode_simple(eng, seed, env, bud, empty, lr, flags):
    return run_episode(seed, env, bud, empty, eng, credit_lr=lr, learn_end=True, surge_flags=flags)


def refine(eng, stats, run_idx):
    I = eng.paradox.intuition
    notes = []
    if (stats.get("alive_end") or 0) < 13:
        I["pairing_strength"] = float(np.clip(float(I.get("pairing_strength", 1)) + 0.03, 0.3, 2.4))
        I["floor_boost"] = float(np.clip(float(I.get("floor_boost", 0.1)) + 0.01, 0.04, 0.35))
        I["damper_bias"] = float(np.clip(float(I.get("damper_bias", 2)) - 0.015, 1.45, 2.28))
        notes.append("revive↑")
    if (stats.get("mean_err_gp") or 0) > 0.016:
        I["predict_trust"] = float(np.clip(float(I.get("predict_trust", 0.7)) + 0.015, 0.2, 0.95))
        notes.append("predict↑")
    if (stats.get("storm_frac_during_surprise") or 0) < 0.9:
        I["countermeasure_invest"] = float(np.clip(float(I.get("countermeasure_invest", 1)) + 0.04, 0.3, 2.0))
        notes.append("cm↑ surprise arm")
    if (stats.get("stab_vs_target") or 0) < -0.01:
        I["repair_bias"] = float(np.clip(float(I.get("repair_bias", 2)) + 0.03, 0.5, 2.4))
        notes.append("repair↑ toward 0.935")
    I["target_coherence"] = TARGET
    eng.credit.lr_scale = float(np.clip(1.05 * (0.9**run_idx), 0.35, 1.3))
    notes.append(f"lr={eng.credit.lr_scale:.2f}")
    return notes


def main():
    print("=" * 72)
    print(f" CREDIT EXAM ×3 @ TARGET {TARGET} + SATURDAY SURPRISE SURGE")
    print("=" * 72)

    engines: dict[int, HealthEngine] = {}
    run_sum = []

    for run in range(1, N_RUNS + 1):
        print(f"\n### RUN {run}/{N_RUNS}")
        pack = {"credit_opt": [], "no_credit": [], "baseline": []}
        for seed in EXAM_SEEDS:
            rng = np.random.default_rng(seed + run * 1000)
            env0, bud0, empty0 = tough_week(rng)
            env, bud, empty, flags = inject_surprise_surge(env0, bud0, empty0)

            pack["baseline"].append(run_baseline(seed, env, bud, empty))

            eng_nc = HealthEngine(
                seed=seed + 10 + run, storm_mode="auto", credit_loop=False, target=TARGET
            )
            pack["no_credit"].append(
                run_episode(seed + 11, env, bud, empty, eng_nc, learn_end=False, surge_flags=flags)
            )

            if seed not in engines:
                engines[seed] = HealthEngine(
                    seed=seed + 20,
                    storm_mode="auto",
                    credit_loop=True,
                    credit_lr=1.2,
                    target=TARGET,
                )
                tr = np.random.default_rng(seed + 50)
                nblock = 3 if run == 1 else 1
                for b in range(nblock):
                    train_block(
                        engines[seed],
                        seed + 100 + b + run * 10,
                        1.15 * (0.88**b) * (0.92 ** (run - 1)),
                        tr,
                    )

            env_e, bud_e, empty_e = tough_week(np.random.default_rng(seed + 200 + run * 17))
            env_e, bud_e, empty_e, flags_e = inject_surprise_surge(env_e, bud_e, empty_e)
            r = run_episode(
                seed + 30 + run,
                env_e,
                bud_e,
                empty_e,
                engines[seed],
                credit_lr=engines[seed].credit.lr_scale,
                learn_end=True,
                surge_flags=flags_e,
            )
            pack["credit_opt"].append(r)
            if run < N_RUNS:
                refine(engines[seed], r, run)

        def mean(arm, key):
            vals = [x[key] for x in pack[arm] if x.get(key) is not None]
            return float(np.mean(vals)) if vals else float("nan")

        summary = {
            arm: {
                k: mean(arm, k)
                for k in (
                    "gp_mean",
                    "alive_end",
                    "stab_late",
                    "stab_vs_target",
                    "mean_err_gp",
                    "mean_regret",
                    "gp_during_surprise",
                    "alive_during_surprise",
                    "storm_frac_during_surprise",
                    "beacon_frac_during_surprise",
                    "damper_during_surprise",
                    "damper_relax_sample",
                    "storm_frac_relax_sample",
                )
                if arm != "baseline" or k in ("gp_mean", "alive_end")
            }
            for arm in pack
        }
        # intuition mean
        keys = list(pack["credit_opt"][0]["intuition"].keys())
        summary["credit_opt"]["intuition"] = {
            k: float(np.mean([r["intuition"][k] for r in pack["credit_opt"]])) for k in keys
        }
        run_sum.append(summary)
        co, nc = summary["credit_opt"], summary["no_credit"]
        print(
            f"  no_cred gp={nc['gp_mean']:.3f} alive={nc['alive_end']:.1f}  "
            f"surge_storm={100*nc['storm_frac_during_surprise']:.0f}%"
        )
        print(
            f"  credit  gp={co['gp_mean']:.3f} alive={co['alive_end']:.1f}  "
            f"stab={co['stab_late']:.3f} gap={co['stab_vs_target']:+.3f}  "
            f"err={co['mean_err_gp']:.3f}"
        )
        print(
            f"  SURPRISE Sat: gp={co['gp_during_surprise']:.3f} alive={co['alive_during_surprise']:.1f}  "
            f"storm={100*co['storm_frac_during_surprise']:.0f}% beacon={100*co['beacon_frac_during_surprise']:.0f}%  "
            f"damper {co['damper_relax_sample']:.2f}→{co['damper_during_surprise']:.2f}"
        )

    print("\n" + "=" * 72)
    print(" PROGRESS @ 0.935 (credit_opt)")
    print("=" * 72)
    print(
        f"  {'run':>3}  {'gp':>6}  {'alive':>6}  {'stab':>6}  {'err':>6}  "
        f"{'surge_gp':>8}  {'surge_storm%':>12}  {'damp_relax→surge':>16}"
    )
    for i, s in enumerate(run_sum, 1):
        c = s["credit_opt"]
        print(
            f"  {i:3d}  {c['gp_mean']:6.3f}  {c['alive_end']:6.1f}  {c['stab_late']:6.3f}  "
            f"{c['mean_err_gp']:6.3f}  {c['gp_during_surprise']:8.3f}  "
            f"{100*c['storm_frac_during_surprise']:11.0f}%  "
            f"{c['damper_relax_sample']:.2f}→{c['damper_during_surprise']:.2f}"
        )

    r1, r3 = run_sum[0]["credit_opt"], run_sum[-1]["credit_opt"]
    print("\n[r3 − r1]")
    print(f"  Δgp={r3['gp_mean']-r1['gp_mean']:+.4f}  Δalive={r3['alive_end']-r1['alive_end']:+.2f}")
    print(f"  Δerr={r3['mean_err_gp']-r1['mean_err_gp']:+.4f}  Δstab={r3['stab_late']-r1['stab_late']:+.4f}")
    print(
        f"  surprise storm arm: {100*r3['storm_frac_during_surprise']:.0f}%  "
        f"beacon {100*r3['beacon_frac_during_surprise']:.0f}%"
    )

    # one detailed response plot seed 21 run3-style
    eng = engines[21]
    rng = np.random.default_rng(999)
    env, bud, empty = tough_week(rng)
    env, bud, empty, flags = inject_surprise_surge(env, bud, empty)
    # fresh series with logging
    eng2 = HealthEngine(seed=21, storm_mode="auto", credit_loop=True, target=TARGET)
    eng2.paradox.intuition.update(engines[21].paradox.intuition)
    w = World(rng=np.random.default_rng(88))
    series = []
    for t in range(len(env)):
        w.budget_mul, w.tool_empty = bud[t], empty[t]
        out = eng2.step_from_metrics(
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
        eng2.observe_actual(goodput=m["gp"], alive_frac=m["alive_frac"], stability=out["stability"])
        series.append(
            {
                "env": env[t],
                "gp": m["gp"],
                "alive": m["alive"] / 28,
                "storm": 1.0 if out["storm_active"] else 0.0,
                "damper": out["damper_live"],
                "surge": 1.0 if flags[t] else 0.0,
                "stab": out["stability"],
            }
        )

    x = np.arange(len(series))
    fig, axes = plt.subplots(4, 1, figsize=(11, 9), sharex=True)
    axes[0].plot(x, [s["env"] for s in series], color="#9b59b6", label="env")
    axes[0].fill_between(x, 0, [2.5 * s["surge"] for s in series], color="#e74c3c", alpha=0.35, label="SURPRISE")
    for i, d in enumerate(DAYS):
        axes[0].axvline(i * STEPS_DAY, color="#333", alpha=0.25)
        axes[0].text(i * STEPS_DAY + 1, 2.5, d, fontsize=7, color="#888")
    axes[0].legend(fontsize=8)
    axes[0].set_ylabel("env")
    axes[0].set_title(f"Surprise Saturday surge response @ target {TARGET}")

    axes[1].plot(x, [s["gp"] for s in series], color="#5dffb0", label="goodput")
    axes[1].plot(x, [s["alive"] for s in series], color="#40d0ff", label="alive frac")
    axes[1].legend(fontsize=8)
    axes[1].set_ylabel("gp / alive")
    axes[1].grid(True, alpha=0.25)

    axes[2].fill_between(x, 0, [s["storm"] for s in series], color="#40d0ff", alpha=0.4, label="storm on")
    axes[2].plot(x, [s["damper"] for s in series], color="#2ecc71", label="live damper")
    axes[2].legend(fontsize=8)
    axes[2].set_ylabel("arsenal")
    axes[2].grid(True, alpha=0.25)

    axes[3].plot(x, [s["stab"] for s in series], color="#f1c40f")
    axes[3].axhline(TARGET, color="#e74c3c", ls="--", label=f"desire {TARGET}")
    axes[3].axhline(0.92, color="#888", ls=":", label="0.92")
    axes[3].legend(fontsize=8)
    axes[3].set_xlabel("step")
    axes[3].set_ylabel("stability")
    fig.tight_layout()
    png = OUT / "paradox_credit_0935_surprise_surge.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # progress bars
    fig2, ax = plt.subplots(figsize=(9, 4))
    xs = [1, 2, 3]
    ax.plot(xs, [s["credit_opt"]["gp_mean"] for s in run_sum], "o-", label="gp")
    ax.plot(xs, [s["credit_opt"]["alive_end"] / 28 for s in run_sum], "s-", label="alive/28")
    ax.plot(xs, [s["credit_opt"]["storm_frac_during_surprise"] for s in run_sum], "^-", label="surge storm%")
    ax.set_xticks(xs)
    ax.set_title(f"Progress @ {TARGET} with surprise surge")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig2.tight_layout()
    png2 = OUT / "paradox_credit_0935_progress.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)

    out = {
        "target": TARGET,
        "surprise": "Saturday hours 10-16 env→2.45 budget→0.42",
        "runs": run_sum,
        "learning_curve": {
            "delta_gp": r3["gp_mean"] - r1["gp_mean"] if False else run_sum[-1]["credit_opt"]["gp_mean"] - run_sum[0]["credit_opt"]["gp_mean"],
            "delta_alive": run_sum[-1]["credit_opt"]["alive_end"] - run_sum[0]["credit_opt"]["alive_end"],
            "delta_err": run_sum[-1]["credit_opt"]["mean_err_gp"] - run_sum[0]["credit_opt"]["mean_err_gp"],
        },
    }
    # fix r1 r3
    r1, r3 = run_sum[0]["credit_opt"], run_sum[-1]["credit_opt"]
    out["learning_curve"] = {
        "delta_gp": r3["gp_mean"] - r1["gp_mean"],
        "delta_alive": r3["alive_end"] - r1["alive_end"],
        "delta_err": r3["mean_err_gp"] - r1["mean_err_gp"],
        "delta_stab": r3["stab_late"] - r1["stab_late"],
        "surprise_storm_r3": r3["storm_frac_during_surprise"],
        "damper_jump_r3": (r3["damper_during_surprise"] or 0) - (r3["damper_relax_sample"] or 0),
    }
    js = OUT / "paradox_credit_exam_0935_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
