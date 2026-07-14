"""
Paradox credit exams @ target coherence 0.93 — 3 learning runs
==============================================================
Desire/target coherence raised to **0.93**.

Run structure (optimized for Paradox credit learning between runs):
  RUN 1  train credit_opt → exam tough week (multi-seed)
  between  refine LR + absorb best practices from run summary
  RUN 2  continue same engines (carry intuition) → exam
  between  refine again (boost revive if alive lag; boost cm if storm regret)
  RUN 3  final exam

Also tracks no_credit frozen baseline each run for comparison.

  python real_world/paradox_credit_exam_093.py
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

# Reuse world/schedules from credit exam
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paradox_credit_exam import (  # noqa: E402
    World,
    apply_plan,
    bright_week,
    tough_week,
    STEPS_DAY,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = 0.93  # desire coherence
N_RUNS = 3
EXAM_SEEDS = [7, 11, 21, 29, 42, 53]


def run_episode(
    *,
    seed: int,
    env,
    bud,
    empty,
    eng: HealthEngine,
    credit_lr: float = 1.0,
    learn_end: bool = True,
) -> dict:
    eng.credit.lr_scale = credit_lr
    eng.credit_loop = True
    eng.target = TARGET
    eng.paradox.intuition["target_coherence"] = TARGET

    w = World(rng=np.random.default_rng(seed + 3))
    gps, alives, stabs = [], [], []
    errs_g, regrets = [], []
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
        stabs.append(out["stability"])
        if obs:
            errs_g.append(obs["err_gp"])
            regrets.append(obs["regret"])
            ba = obs["best_action"]
            best_counts[ba] = best_counts.get(ba, 0) + 1

    credit_report = eng.end_episode_credit() if learn_end else {}
    gp = np.array(gps)
    al = np.array(alives, float)
    st = np.array(stabs)
    return {
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "stab_mean": float(np.mean(st)),
        "stab_late": float(np.mean(st[-STEPS_DAY:])),
        "stab_vs_target": float(np.mean(st[-STEPS_DAY:]) - TARGET),
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
                "target_coherence",
            )
        },
    }


def run_baseline(seed, env, bud, empty) -> dict:
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
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(al[-1]),
        "alive_mean": float(np.mean(al)),
        "stab_mean": None,
        "stab_late": None,
        "stab_vs_target": None,
        "mean_err_gp": None,
        "mean_regret": None,
    }


def train_block(eng: HealthEngine, seed: int, lr: float, rng: np.random.Generator) -> None:
    """One optimized credit train block: bright → tough → tough."""
    eng.credit.lr_scale = lr
    for i, sched_fn in enumerate((bright_week, tough_week, tough_week)):
        r = rng if i < 2 else np.random.default_rng(int(rng.integers(1e9)))
        env, bud, empty = sched_fn(r)
        run_episode(
            seed=seed + i,
            env=env,
            bud=bud,
            empty=empty,
            eng=eng,
            credit_lr=lr * (0.9 if i else 1.0) * (0.8 if i == 2 else 1.0),
            learn_end=True,
        )


def refine_between_runs(eng: HealthEngine, run_stats: dict, run_idx: int) -> dict:
    """
    Optimize Paradox learning between exam runs based on aggregate stats.
    """
    notes = []
    I = eng.paradox.intuition
    alive = run_stats.get("alive_end", 12)
    err = run_stats.get("mean_err_gp", 0.02) or 0.02
    gp = run_stats.get("gp_mean", 0.24)
    stab_gap = run_stats.get("stab_vs_target", -0.01) or -0.01
    regret = run_stats.get("mean_regret", 0.05) or 0.05

    # If below desire band, push repair toward 0.93
    if stab_gap < -0.02:
        old = float(I.get("repair_bias", 2.0))
        I["repair_bias"] = float(np.clip(old + 0.04, 0.5, 2.4))
        notes.append(f"repair↑ for target 0.93 (gap={stab_gap:.3f})")

    # Survival lag → revive path
    if alive < 13.0:
        I["pairing_strength"] = float(np.clip(float(I.get("pairing_strength", 1.0)) + 0.035, 0.3, 2.2))
        I["floor_boost"] = float(np.clip(float(I.get("floor_boost", 0.1)) + 0.012, 0.04, 0.35))
        I["damper_bias"] = float(np.clip(float(I.get("damper_bias", 2.0)) - 0.02, 1.45, 2.28))
        notes.append("revive path↑ (alive lag)")

    # Forecast still noisy → slight predict_trust / failure_respect
    if err > 0.018:
        I["predict_trust"] = float(np.clip(float(I.get("predict_trust", 0.7)) + 0.02, 0.2, 0.95))
        notes.append("predict_trust↑ (err_gp high)")

    # High residual regret → countermeasure (storm earlier)
    if regret > 0.04:
        I["countermeasure_invest"] = float(
            np.clip(float(I.get("countermeasure_invest", 1.0)) + 0.03, 0.3, 2.0)
        )
        notes.append("cm↑ (regret)")

    # Good week → bright competence (don't freeze)
    if gp >= 0.245 and alive >= 13:
        I["explore_bias"] = float(np.clip(float(I.get("explore_bias", 0.1)) + 0.01, 0.06, 0.45))
        notes.append("explore↑ (solid week)")

    I["target_coherence"] = TARGET
    # next run LR: start higher if still learning, decay if stable
    next_lr = 1.1 * (0.88**run_idx)
    if err > 0.02:
        next_lr *= 1.1
    if alive < 12:
        next_lr *= 1.05
    eng.credit.lr_scale = float(np.clip(next_lr, 0.35, 1.35))
    notes.append(f"next_lr={eng.credit.lr_scale:.2f}")

    eng.paradox.wisdom["exam_093"] = (
        f"run{run_idx} refine: desire=0.93; " + "; ".join(notes)
    )
    return {"notes": notes, "next_lr": eng.credit.lr_scale, "intuition": dict(I)}


def exam_once(engines: dict[int, HealthEngine], run_idx: int, train_blocks: int) -> dict:
    """One full multi-seed exam; engines carry state for credit_opt arm."""
    rows = {"baseline": [], "no_credit": [], "credit_opt": []}

    for seed in EXAM_SEEDS:
        rng = np.random.default_rng(seed + run_idx * 1000)
        env, bud, empty = tough_week(rng)

        # baseline
        rows["baseline"].append(run_baseline(seed, env, bud, empty))

        # no_credit fresh each time (control)
        eng_nc = HealthEngine(
            seed=seed + 10 + run_idx,
            storm_mode="auto",
            weekly_drill=True,
            credit_loop=False,
            target=TARGET,
        )
        r_nc = run_episode(
            seed=seed + 11,
            env=env,
            bud=bud,
            empty=empty,
            eng=eng_nc,
            learn_end=False,
        )
        rows["no_credit"].append(r_nc)

        # credit_opt: persistent engine per seed
        if seed not in engines:
            engines[seed] = HealthEngine(
                seed=seed + 20,
                storm_mode="auto",
                weekly_drill=True,
                credit_loop=True,
                credit_lr=1.2,
                target=TARGET,
            )
            # initial train
            trng = np.random.default_rng(seed + 50)
            for b in range(train_blocks):
                lr = 1.2 * (0.88**b) * (0.92 ** (run_idx - 1))
                train_block(engines[seed], seed + 100 + b + run_idx * 10, lr, trng)

        # inter-run refine already applied to eng between runs
        env_e, bud_e, empty_e = tough_week(np.random.default_rng(seed + 200 + run_idx * 17))
        r_o = run_episode(
            seed=seed + 30 + run_idx,
            env=env_e,
            bud=bud_e,
            empty=empty_e,
            eng=engines[seed],
            credit_lr=engines[seed].credit.lr_scale,
            learn_end=True,
        )
        # extra micro-train after exam (learn from this tough week before next run)
        if run_idx < N_RUNS:
            trng2 = np.random.default_rng(seed + 300 + run_idx)
            train_block(
                engines[seed],
                seed + 400 + run_idx,
                max(0.4, engines[seed].credit.lr_scale * 0.85),
                trng2,
            )
        rows["credit_opt"].append(r_o)

    def mean(arm, key):
        vals = [r[key] for r in rows[arm] if r.get(key) is not None]
        return float(np.mean(vals)) if vals else float("nan")

    summary = {
        arm: {
            k: mean(arm, k)
            for k in (
                "gp_mean",
                "gp_sun",
                "alive_end",
                "stab_late",
                "stab_vs_target",
                "mean_err_gp",
                "mean_regret",
            )
        }
        for arm in rows
    }
    # aggregate best_counts for credit_opt
    bc: dict[str, int] = {}
    for r in rows["credit_opt"]:
        for k, v in (r.get("best_counts") or {}).items():
            bc[k] = bc.get(k, 0) + v
    summary["credit_opt"]["best_counts"] = bc
    # mean intuition
    keys = list(rows["credit_opt"][0]["intuition"].keys())
    summary["credit_opt"]["intuition"] = {
        k: float(np.mean([r["intuition"][k] for r in rows["credit_opt"]])) for k in keys
    }
    return summary, rows, engines


def main():
    print("=" * 72)
    print(f" PARADOX CREDIT EXAM × {N_RUNS} @ TARGET COHERENCE {TARGET:.2f}")
    print(" learn between runs · optimize credit LR & intuition refine")
    print("=" * 72)

    engines: dict[int, HealthEngine] = {}
    run_summaries = []
    train_blocks_run1 = 3

    for run in range(1, N_RUNS + 1):
        print(f"\n{'#'*72}\n# RUN {run}/{N_RUNS}\n{'#'*72}")
        # slightly fewer initial blocks after run1 (engines already warm)
        tb = train_blocks_run1 if run == 1 else 1
        summary, rows, engines = exam_once(engines, run, tb)
        run_summaries.append(summary)

        co = summary["credit_opt"]
        nc = summary["no_credit"]
        print(
            f"  no_credit   gp={nc['gp_mean']:.3f} alive={nc['alive_end']:.1f}"
        )
        print(
            f"  credit_opt  gp={co['gp_mean']:.3f} alive={co['alive_end']:.1f}  "
            f"stab_late={co['stab_late']:.3f} (target {TARGET}) gap={co['stab_vs_target']:+.3f}  "
            f"err_gp={co['mean_err_gp']:.3f} regret={co['mean_regret']:.3f}"
        )
        print(f"  Δgp vs nc={co['gp_mean']-nc['gp_mean']:+.3f}  Δalive={co['alive_end']-nc['alive_end']:+.2f}")

        if run < N_RUNS:
            # refine each seed engine from this run's per-seed stats
            refine_notes = []
            for i, seed in enumerate(EXAM_SEEDS):
                rstat = rows["credit_opt"][i]
                ref = refine_between_runs(engines[seed], rstat, run)
                refine_notes.append(ref["notes"])
            print(f"  between-run refine (seed0): {refine_notes[0]}")

    # Progress table
    print("\n" + "=" * 72)
    print(" PROGRESS REPORT (credit_opt across 3 runs)")
    print("=" * 72)
    print(
        f"  {'run':>4s}  {'gp_mean':>8s}  {'alive':>7s}  {'stab_late':>9s}  "
        f"{'gap_to_0.93':>11s}  {'err_gp':>8s}  {'regret':>8s}  {'Δgp_nc':>8s}"
    )
    for i, s in enumerate(run_summaries, 1):
        co, nc = s["credit_opt"], s["no_credit"]
        print(
            f"  {i:4d}  {co['gp_mean']:8.3f}  {co['alive_end']:7.2f}  {co['stab_late']:9.3f}  "
            f"{co['stab_vs_target']:+11.3f}  {co['mean_err_gp']:8.3f}  {co['mean_regret']:8.3f}  "
            f"{co['gp_mean']-nc['gp_mean']:+8.3f}"
        )

    r1 = run_summaries[0]["credit_opt"]
    r3 = run_summaries[-1]["credit_opt"]
    print("\n[LEARNING CURVE r3 − r1]")
    print(f"  Δgp_mean:     {r3['gp_mean']-r1['gp_mean']:+.4f}")
    print(f"  Δalive_end:   {r3['alive_end']-r1['alive_end']:+.2f}")
    print(f"  Δstab_late:   {r3['stab_late']-r1['stab_late']:+.4f}")
    print(f"  Δerr_gp:      {r3['mean_err_gp']-r1['mean_err_gp']:+.4f}  (want negative)")
    print(f"  Δregret:      {r3['mean_regret']-r1['mean_regret']:+.4f}  (want negative)")
    print(f"  Δgap_to_0.93: {r3['stab_vs_target']-r1['stab_vs_target']:+.4f}  (want toward 0)")

    print("\n[INTUITION drift run1 → run3 mean]")
    for k in r1["intuition"]:
        print(f"  {k:24s}  {r1['intuition'][k]:.3f} → {r3['intuition'][k]:.3f}")

    # refinements
    refinements = []
    if r3["mean_err_gp"] < r1["mean_err_gp"] - 0.001:
        refinements.append("Forecast skill improved across runs — keep multi-run carry.")
    else:
        refinements.append("Forecast error flat — increase bright weeks in between-run train_block.")
    if r3["alive_end"] > r1["alive_end"] + 0.3:
        refinements.append("Survival climbed — revive/refine path is working.")
    elif r3["alive_end"] < r1["alive_end"] - 0.5:
        refinements.append("Survival slipped — strengthen revive CF weight further; cut cool lessons.")
    if r3["stab_vs_target"] > r1["stab_vs_target"]:
        refinements.append("Closer to 0.93 desire band — repair nudges helping.")
    else:
        refinements.append("Still below 0.93 late stab — raise repair/floor_boost in refine or install gain.")
    if r3["gp_mean"] + 0.005 >= run_summaries[-1]["no_credit"]["gp_mean"]:
        refinements.append("Control parity vs no_credit held at 0.93 target.")
    else:
        refinements.append("gp lag vs no_credit — exam with freeze credit_lr at end of each run.")
    refinements.append("Optional: log best_action histograms per run to retune CF heuristics.")
    refinements.append("Optional: separate predict-head LR from control-intuition LR.")
    refinements.append("Optional: Soft Pack stays at 0.92 desire until multi-seed promote exam freezes 0.93.")

    print("\n[FURTHER REFINEMENT OPTIONS]")
    for i, x in enumerate(refinements, 1):
        print(f"  {i}. {x}")

    # plot progress
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    xs = [1, 2, 3]
    co_gp = [s["credit_opt"]["gp_mean"] for s in run_summaries]
    nc_gp = [s["no_credit"]["gp_mean"] for s in run_summaries]
    co_al = [s["credit_opt"]["alive_end"] for s in run_summaries]
    co_err = [s["credit_opt"]["mean_err_gp"] for s in run_summaries]
    co_stab = [s["credit_opt"]["stab_late"] for s in run_summaries]

    axes[0, 0].plot(xs, co_gp, "o-", color="#2ecc71", label="credit_opt")
    axes[0, 0].plot(xs, nc_gp, "s--", color="#5dffb0", label="no_credit")
    axes[0, 0].set_title(f"Goodput @ target {TARGET}")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(True, alpha=0.25)
    axes[0, 0].set_xticks(xs)

    axes[0, 1].plot(xs, co_al, "o-", color="#40d0ff")
    axes[0, 1].set_title("End alive (credit_opt)")
    axes[0, 1].grid(True, alpha=0.25)
    axes[0, 1].set_xticks(xs)

    axes[1, 0].plot(xs, co_err, "o-", color="#e67e22")
    axes[1, 0].set_title("Forecast err_gp (lower better)")
    axes[1, 0].grid(True, alpha=0.25)
    axes[1, 0].set_xticks(xs)

    axes[1, 1].plot(xs, co_stab, "o-", color="#9b59b6", label="stab_late")
    axes[1, 1].axhline(TARGET, color="#e74c3c", ls="--", label="desire 0.93")
    axes[1, 1].axhline(0.92, color="#888", ls=":", label="old 0.92")
    axes[1, 1].set_title("Late stability vs desire")
    axes[1, 1].legend(fontsize=7)
    axes[1, 1].grid(True, alpha=0.25)
    axes[1, 1].set_xticks(xs)

    fig.suptitle("Paradox credit learning progress (3 runs @ 0.93)")
    fig.tight_layout()
    png = OUT / "paradox_credit_exam_093_progress.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "target_coherence": TARGET,
        "n_runs": N_RUNS,
        "exam_seeds": EXAM_SEEDS,
        "runs": run_summaries,
        "learning_curve": {
            "delta_gp": r3["gp_mean"] - r1["gp_mean"],
            "delta_alive": r3["alive_end"] - r1["alive_end"],
            "delta_stab_late": r3["stab_late"] - r1["stab_late"],
            "delta_err_gp": r3["mean_err_gp"] - r1["mean_err_gp"],
            "delta_regret": r3["mean_regret"] - r1["mean_regret"],
            "delta_gap": r3["stab_vs_target"] - r1["stab_vs_target"],
        },
        "refinements": refinements,
        "note": "KERNEL default TARGET still 0.92; exam uses HealthEngine(target=0.93)",
    }
    js = OUT / "paradox_credit_exam_093_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
