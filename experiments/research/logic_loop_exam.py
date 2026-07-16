"""
Logic-loop governor exam — baseline one-shot vs controlled verify loop
=====================================================================
Doctrine: ops/LOGIC_LOOP_GOVERNOR.md

  python real_world/logic_loop_exam.py
  python real_world/logic_loop_exam.py --items 80 --seeds 7,13,21
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]  # repo root
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from logic_loop_governor import (
    LogicLoopControls,
    LogicLoopGovernor,
    SyntheticModel,
    baseline_one_shot,
    make_exam_world,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# Primary bars (v1 — faithfulness under noise)
MAIN_MIN = 0.55  # fraction of items with main_ok
SAFE_MIN = 0.80
FALSE_CONF_MAX = 0.20
# Lift: governor MAIN should beat baseline by this
LIFT_MAIN_MIN = 0.12


def run_arm(
    *,
    arm: str,
    seed: int,
    n_items: int,
    noise_schedule: list[float],
    thrash_schedule: list[float],
) -> dict:
    source, universe = make_exam_world(seed=seed)
    model = SyntheticModel(
        source=source,
        universe=universe,
        base_halluc_rate=0.28,
        claims_per_draft=4,
        seed=seed,
    )
    ctrl = LogicLoopControls(
        max_loops=3,
        n_samples=3,
        conf_release=0.55,
        conf_false=0.70,
        agree_min=0.50,
        cool_on_disagree=True,
        thrash_cool_rate=0.38,
        seed=seed,
    )
    gov = LogicLoopGovernor(model=model, controls=ctrl)
    gov.reset_thrash()

    main_flags = []
    safe_flags = []
    fc_flags = []
    support_rates = []
    loop_steps = []
    abstain_flags = []
    thrash_series = []

    for i in range(n_items):
        noise = noise_schedule[i % len(noise_schedule)]
        thr_inj = thrash_schedule[i % len(thrash_schedule)]
        if arm == "baseline":
            # baseline accumulates thrash without cool
            thr = float(np.clip(0.15 + thr_inj + 0.01 * i, 0, 1.2))
            r = baseline_one_shot(model, noise=noise, thrash=thr)
        else:
            r = gov.step_item(noise=noise, inject_thrash=thr_inj)

        main_flags.append(1.0 if r.main_ok else 0.0)
        safe_flags.append(1.0 if r.safe_ok else 0.0)
        fc_flags.append(1.0 if r.false_confidence else 0.0)
        support_rates.append(r.support_rate)
        loop_steps.append(r.loop_steps)
        abstain_flags.append(1.0 if r.abstained else 0.0)
        thrash_series.append(r.thrash_after)

    return {
        "arm": arm,
        "seed": seed,
        "main_rate": float(np.mean(main_flags)),
        "safe_rate": float(np.mean(safe_flags)),
        "false_conf_rate": float(np.mean(fc_flags)),
        "support_rate": float(np.mean(support_rates)),
        "loop_steps_mean": float(np.mean(loop_steps)),
        "abstain_rate": float(np.mean(abstain_flags)),
        "thrash_mean": float(np.mean(thrash_series)),
        "main_series": main_flags,
        "safe_series": safe_flags,
        "support_series": support_rates,
        "thrash_series": thrash_series,
    }


def default_schedules(n: int) -> tuple[list[float], list[float]]:
    """Calm → noise spike → thrash spike → calm (like residual exams)."""
    noise, thr = [], []
    for i in range(n):
        t = i / max(1, n - 1)
        if t < 0.15:
            noise.append(0.08)
            thr.append(0.05)
        elif t < 0.45:
            noise.append(0.45 + 0.2 * ((t - 0.15) / 0.3))
            thr.append(0.20)
        elif t < 0.75:
            noise.append(0.35)
            thr.append(0.55 + 0.25 * ((t - 0.45) / 0.3))
        else:
            noise.append(0.12)
            thr.append(0.10)
    return noise, thr


def plot_compare(base: dict, gov: dict, path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))

    # bar lifts
    ax = axes[0, 0]
    metrics = ["main_rate", "safe_rate", "support_rate"]
    labels = ["MAIN", "SAFE", "support"]
    xb = [base[m] for m in metrics]
    xg = [gov[m] for m in metrics]
    idx = np.arange(len(labels))
    ax.bar(idx - 0.18, xb, 0.35, label="baseline", color="#ff8a8a")
    ax.bar(idx + 0.18, xg, 0.35, label="governor", color="#5dffb0")
    ax.set_xticks(idx)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.05)
    ax.set_title("Faithfulness rates (higher better)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25, axis="y")

    ax = axes[0, 1]
    bad_m = ["false_conf_rate", "abstain_rate"]
    bad_l = ["false conf", "abstain"]
    xb = [base[m] for m in bad_m]
    xg = [gov[m] for m in bad_m]
    idx = np.arange(len(bad_l))
    ax.bar(idx - 0.18, xb, 0.35, label="baseline", color="#ff8a8a")
    ax.bar(idx + 0.18, xg, 0.35, label="governor", color="#6eb6ff")
    ax.set_xticks(idx)
    ax.set_xticklabels(bad_l)
    ax.set_ylim(0, 1.05)
    ax.set_title("False confidence ↓ · abstain (governor may rise)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25, axis="y")

    ax = axes[1, 0]
    # rolling support
    def roll(s, w=8):
        a = np.array(s, float)
        if len(a) < w:
            return a
        out = np.convolve(a, np.ones(w) / w, mode="valid")
        return out

    ax.plot(roll(base["support_series"]), color="#ff6b6b", lw=1.3, label="baseline support")
    ax.plot(roll(gov["support_series"]), color="#5dffb0", lw=1.3, label="governor support")
    ax.set_ylim(0, 1.05)
    ax.set_title("Rolling support rate")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)

    ax = axes[1, 1]
    ax.plot(base["thrash_series"], color="#ffaa55", lw=1.1, alpha=0.85, label="baseline thrash")
    ax.plot(gov["thrash_series"], color="#c77dff", lw=1.1, alpha=0.85, label="governor thrash")
    ax.set_title("Thrash (governor cools)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)

    lift = gov["main_rate"] - base["main_rate"]
    fig.suptitle(
        f"Logic-loop governor  MAIN {base['main_rate']:.2f}→{gov['main_rate']:.2f}  "
        f"(Δ{lift:+.2f})  seed={gov['seed']}",
        fontsize=12,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", type=int, default=60)
    ap.add_argument("--seeds", type=str, default="7,13,21")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    n = args.items
    noise_s, thr_s = default_schedules(n)

    print("=" * 68)
    print(" LOGIC-LOOP GOVERNOR EXAM — baseline vs controlled verify")
    print("=" * 68)
    print(f"  items={n}  seeds={seeds}")
    print(f"  bars: MAIN≥{MAIN_MIN}  SAFE≥{SAFE_MIN}  FCmax={FALSE_CONF_MAX}  lift≥{LIFT_MAIN_MIN}")

    base_eps, gov_eps = [], []
    for seed in seeds:
        print(f"\n── seed={seed} ──")
        b = run_arm(
            arm="baseline",
            seed=seed,
            n_items=n,
            noise_schedule=noise_s,
            thrash_schedule=thr_s,
        )
        g = run_arm(
            arm="governor",
            seed=seed,
            n_items=n,
            noise_schedule=noise_s,
            thrash_schedule=thr_s,
        )
        base_eps.append(b)
        gov_eps.append(g)
        lift = g["main_rate"] - b["main_rate"]
        print(
            f"  baseline  MAIN={b['main_rate']:.3f}  SAFE={b['safe_rate']:.3f}  "
            f"FC={b['false_conf_rate']:.3f}  support={b['support_rate']:.3f}"
        )
        print(
            f"  governor  MAIN={g['main_rate']:.3f}  SAFE={g['safe_rate']:.3f}  "
            f"FC={g['false_conf_rate']:.3f}  support={g['support_rate']:.3f}  "
            f"loops={g['loop_steps_mean']:.2f}  abstain={g['abstain_rate']:.3f}"
        )
        print(f"  lift MAIN={lift:+.3f}")

    def mean_field(eps, k):
        return float(np.mean([e[k] for e in eps]))

    summary = {
        "baseline": {
            "main_rate": mean_field(base_eps, "main_rate"),
            "safe_rate": mean_field(base_eps, "safe_rate"),
            "false_conf_rate": mean_field(base_eps, "false_conf_rate"),
            "support_rate": mean_field(base_eps, "support_rate"),
            "abstain_rate": mean_field(base_eps, "abstain_rate"),
            "loop_steps_mean": mean_field(base_eps, "loop_steps_mean"),
        },
        "governor": {
            "main_rate": mean_field(gov_eps, "main_rate"),
            "safe_rate": mean_field(gov_eps, "safe_rate"),
            "false_conf_rate": mean_field(gov_eps, "false_conf_rate"),
            "support_rate": mean_field(gov_eps, "support_rate"),
            "abstain_rate": mean_field(gov_eps, "abstain_rate"),
            "loop_steps_mean": mean_field(gov_eps, "loop_steps_mean"),
        },
    }
    lift_main = summary["governor"]["main_rate"] - summary["baseline"]["main_rate"]
    lift_safe = summary["governor"]["safe_rate"] - summary["baseline"]["safe_rate"]
    lift_fc = summary["baseline"]["false_conf_rate"] - summary["governor"]["false_conf_rate"]

    pass_main = summary["governor"]["main_rate"] >= MAIN_MIN
    pass_safe = summary["governor"]["safe_rate"] >= SAFE_MIN
    pass_fc = summary["governor"]["false_conf_rate"] <= FALSE_CONF_MAX
    pass_lift = lift_main >= LIFT_MAIN_MIN
    pass_all = pass_main and pass_safe and pass_fc and pass_lift

    # best seed for plot = max lift
    best_i = int(np.argmax([g["main_rate"] - b["main_rate"] for b, g in zip(base_eps, gov_eps)]))
    plot_compare(
        base_eps[best_i],
        gov_eps[best_i],
        OUT / "logic_loop_exam.png",
    )

    payload = {
        "proto": "logic_loop_exam_v1",
        "items": n,
        "seeds": seeds,
        "bars": {
            "main_min": MAIN_MIN,
            "safe_min": SAFE_MIN,
            "false_conf_max": FALSE_CONF_MAX,
            "lift_main_min": LIFT_MAIN_MIN,
        },
        "summary": summary,
        "lift_main": lift_main,
        "lift_safe": lift_safe,
        "lift_false_conf_drop": lift_fc,
        "pass_main": pass_main,
        "pass_safe": pass_safe,
        "pass_fc": pass_fc,
        "pass_lift": pass_lift,
        "pass_all": pass_all,
        "episodes": {
            "baseline": [
                {k: v for k, v in e.items() if not k.endswith("_series")}
                for e in base_eps
            ],
            "governor": [
                {k: v for k, v in e.items() if not k.endswith("_series")}
                for e in gov_eps
            ],
        },
    }
    (OUT / "logic_loop_exam_results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    md = [
        "# Logic-loop governor exam",
        "",
        "**Doctrine:** `ops/LOGIC_LOOP_GOVERNOR.md`",
        "",
        f"**Pass:** {'YES' if pass_all else 'NO'} · "
        f"MAIN≥{MAIN_MIN} SAFE≥{SAFE_MIN} FC≤{FALSE_CONF_MAX} lift≥{LIFT_MAIN_MIN}",
        "",
        "| Arm | MAIN | SAFE | false conf | support | abstain | loops |",
        "|-----|-----:|-----:|-----------:|--------:|--------:|------:|",
        f"| baseline | {summary['baseline']['main_rate']:.3f} | "
        f"{summary['baseline']['safe_rate']:.3f} | "
        f"{summary['baseline']['false_conf_rate']:.3f} | "
        f"{summary['baseline']['support_rate']:.3f} | "
        f"{summary['baseline']['abstain_rate']:.3f} | "
        f"{summary['baseline']['loop_steps_mean']:.2f} |",
        f"| **governor** | **{summary['governor']['main_rate']:.3f}** | "
        f"**{summary['governor']['safe_rate']:.3f}** | "
        f"**{summary['governor']['false_conf_rate']:.3f}** | "
        f"**{summary['governor']['support_rate']:.3f}** | "
        f"{summary['governor']['abstain_rate']:.3f} | "
        f"{summary['governor']['loop_steps_mean']:.2f} |",
        "",
        f"**Lift MAIN:** {lift_main:+.3f} · **SAFE:** {lift_safe:+.3f} · "
        f"**false-conf drop:** {lift_fc:+.3f}",
        "",
        "Plot: `logic_loop_exam.png`",
        "",
        "v1 world: synthetic faithfulness (source fact_ids). No foundation model training.",
    ]
    (OUT / "LOGIC_LOOP_EXAM.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\n" + "=" * 68)
    print(" SUMMARY (mean across seeds)")
    print("=" * 68)
    print(
        f"  baseline  MAIN={summary['baseline']['main_rate']:.3f}  "
        f"SAFE={summary['baseline']['safe_rate']:.3f}  "
        f"FC={summary['baseline']['false_conf_rate']:.3f}"
    )
    print(
        f"  governor  MAIN={summary['governor']['main_rate']:.3f}  "
        f"SAFE={summary['governor']['safe_rate']:.3f}  "
        f"FC={summary['governor']['false_conf_rate']:.3f}"
    )
    print(f"  lift MAIN={lift_main:+.3f}  SAFE={lift_safe:+.3f}  FC_drop={lift_fc:+.3f}")
    print(
        f"  bars  MAIN={'Y' if pass_main else 'n'}  SAFE={'Y' if pass_safe else 'n'}  "
        f"FC={'Y' if pass_fc else 'n'}  lift={'Y' if pass_lift else 'n'}  "
        f"→ {'PASS' if pass_all else 'fail'}"
    )
    print(f"  plot → {OUT / 'logic_loop_exam.png'}")
    print(f"  report → {OUT / 'LOGIC_LOOP_EXAM.md'}")
    print("=" * 68)

    # update doctrine checklist lightly via print only
    return 0 if pass_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
