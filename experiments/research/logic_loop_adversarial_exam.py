"""
Logic-loop ADVERSARIAL exam — poison / conflict / multi-hop / thrash stampede
==============================================================================
v1 was too soft (+0.98). This tries to break the governor.

Modes (chained in one campaign):
  poison     — retrieved source includes false facts; score vs ground truth
  conflict   — two sources disagree; release only intersection (else abstain)
  multi_hop  — model asserts derived facts not in source; must not release
  stampede   — extreme noise + thrash inject (revise thrash)

  python real_world/logic_loop_adversarial_exam.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from logic_loop_governor import (
    Claim,
    FactSource,
    LogicLoopControls,
    LogicLoopGovernor,
    SyntheticModel,
    baseline_one_shot,
    make_exam_world,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

SEEDS = [7, 13, 21, 29]
ITEMS_PER_MODE = 40

# Chewy bars — lower MAIN OK if SAFE+abstain honest under poison
MAIN_MIN = 0.45
SAFE_MIN = 0.85
FC_MAX = 0.12
LIFT_MAIN_MIN = 0.15
# Under poison/conflict: governor must abstain more than baseline
ABSTAIN_EDGE_MIN = 0.05


def true_support(claim: Claim, truth: FactSource) -> bool:
    return truth.supports(claim.fact_id)


def score_against_truth(released: list[Claim], abstained: bool, truth: FactSource) -> dict:
    if not released:
        return {
            "main_ok": False,
            "safe_ok": bool(abstained),  # abstain OK
            "support_rate": 1.0 if abstained else 0.0,
            "false_confidence": False,
            "unsafe": False,
        }
    n_sup = sum(1 for c in released if true_support(c, truth))
    unsafe = any(not true_support(c, truth) for c in released)
    fc = any(
        (not true_support(c, truth)) and c.confidence >= 0.70 for c in released
    )
    return {
        "main_ok": (n_sup == len(released) and len(released) > 0),
        "safe_ok": not unsafe,
        "support_rate": n_sup / max(1, len(released)),
        "false_confidence": fc,
        "unsafe": unsafe,
    }


def build_mode_world(mode: str, seed: int):
    """
    Return (model, verify_sources, truth, note, source_policy).

    Poison/conflict: dual retrievals; governor uses policy=all (intersection).
    Model still *believes* the union (so it tries to assert poison) — product fix
    is multi-source grounding, not trusting a single polluted doc.
    """
    rng = np.random.default_rng(seed + hash(mode) % 10007)
    truth, universe = make_exam_world(seed=seed, n_facts=14, n_source=7)
    truth_ids = set(truth.fact_ids)
    ghosts = [f"halluc_{i}" for i in range(8)]
    universe = list(universe) + ghosts

    if mode == "poison":
        # Two independent retrievals, *different* poison each.
        # Intersection ≈ ground truth (product: dual retrieval / multi-evidence).
        poison_a = set(rng.choice(ghosts, size=3, replace=False))
        remain = [g for g in ghosts if g not in poison_a]
        poison_b = set(rng.choice(remain, size=min(3, len(remain)), replace=False))
        ret_a = FactSource("retrieve_a", set(truth_ids) | poison_a)
        ret_b = FactSource("retrieve_b", set(truth_ids) | poison_b)
        believed = FactSource(
            "union_poison_belief", set(truth_ids) | poison_a | poison_b
        )
        model = SyntheticModel(
            source=believed,
            universe=list(truth_ids) + list(poison_a | poison_b) * 2 + ghosts,
            base_halluc_rate=0.22,
            claims_per_draft=5,
            seed=seed,
        )
        return model, [ret_a, ret_b], truth, "poison_dual_retrieval", "all"

    if mode == "conflict":
        # Shared core (truth) + exclusive claims per doc (must not release exclusives).
        all_t = list(truth_ids)
        rng.shuffle(all_t)
        n_core = max(2, len(all_t) // 2)
        core = set(all_t[:n_core])
        rest = all_t[n_core:]
        half = max(0, len(rest) // 2)
        src_a = FactSource(
            "doc_a", core | set(rest[:half]) | {ghosts[0], ghosts[1]}
        )
        src_b = FactSource(
            "doc_b", core | set(rest[half:]) | {ghosts[2], ghosts[3]}
        )
        inter = src_a.fact_ids & src_b.fact_ids
        truth_c = FactSource("intersection", set(inter) if inter else set(core))
        believed = FactSource("union_conflict", src_a.fact_ids | src_b.fact_ids)
        model = SyntheticModel(
            source=believed,
            universe=list(believed.fact_ids) + ghosts,
            base_halluc_rate=0.15,
            claims_per_draft=5,
            seed=seed,
        )
        return model, [src_a, src_b], truth_c, "conflict_dual_source", "all"

    if mode == "multi_hop":
        presented = truth
        model = SyntheticModel(
            source=presented,
            universe=list(universe) + [f"hop_derived_{i}" for i in range(6)],
            base_halluc_rate=0.45,
            claims_per_draft=5,
            seed=seed,
        )
        return model, [presented], truth, "multi_hop_invent", "all"

    # stampede
    presented = truth
    model = SyntheticModel(
        source=presented,
        universe=universe,
        base_halluc_rate=0.40,
        claims_per_draft=6,
        seed=seed,
    )
    return model, [presented], truth, "thrash_stampede", "all"


def run_governor_item(
    model,
    truth,
    verify_sources: list,
    source_policy: str,
    mode: str,
    noise: float,
    thrash_inj: float,
    seed: int,
    i: int,
):
    multi = len(verify_sources) > 1
    ctrl = LogicLoopControls(
        max_loops=3 if mode != "stampede" else 2,
        n_samples=3,
        conf_release=0.55,
        conf_false=0.70,
        agree_min=0.55 if mode != "conflict" else 0.58,
        cool_on_disagree=True,
        thrash_cool_rate=0.40,
        seed=seed + i,
        source_policy=source_policy if multi else "all",
        min_source_frac=0.67,
        conflict_disagreement_thresh=0.30,
        conflict_agree_boost=0.12,
    )
    gov = LogicLoopGovernor(
        model=model,
        controls=ctrl,
        sources=list(verify_sources) if multi else None,
    )
    # single-source modes: sources=None → model.source (clean truth)
    if not multi:
        gov.sources = None
    gov.thrash = thrash_inj * 0.5
    r = gov.step_item(noise=noise, inject_thrash=thrash_inj)

    sc = score_against_truth(r.released, r.abstained, truth)
    # FC only on *released* ungrounded high-conf (not verify-time suspects we dropped)
    fc = bool(sc["false_confidence"])
    if r.released:
        fc = fc or bool(r.false_confidence)
    return {
        "main_ok": sc["main_ok"],
        "safe_ok": sc["safe_ok"],
        "support_rate": sc["support_rate"],
        "false_confidence": fc,
        "abstained": r.abstained or (len(r.released) == 0),
        "loop_steps": r.loop_steps,
        "released_n": len(r.released),
    }


def run_baseline_item(model, truth, noise: float, thrash: float):
    r = baseline_one_shot(model, noise=noise, thrash=thrash, conf_release=0.35)
    sc = score_against_truth(r.released, False, truth)
    return {
        "main_ok": sc["main_ok"],
        "safe_ok": sc["safe_ok"],
        "support_rate": sc["support_rate"],
        "false_confidence": sc["false_confidence"],
        "abstained": False,
        "loop_steps": 1,
        "released_n": len(r.released),
    }


def run_mode(mode: str, seed: int) -> dict:
    model, verify_sources, truth, note, policy = build_mode_world(mode, seed)
    base_rows, gov_rows = [], []
    for i in range(ITEMS_PER_MODE):
        if mode == "stampede":
            noise, thr = 0.65, 0.70 + 0.01 * (i % 10)
        elif mode == "poison":
            noise, thr = 0.35, 0.25
        elif mode == "conflict":
            noise, thr = 0.30, 0.20
        else:
            noise, thr = 0.40, 0.30
        # re-seed model draft path
        model.seed = seed + i * 3
        model._rng = np.random.default_rng(model.seed)
        b = run_baseline_item(model, truth, noise, thr)
        # fresh model rng for gov
        model._rng = np.random.default_rng(model.seed + 99)
        g = run_governor_item(
            model,
            truth,
            verify_sources,
            policy,
            mode,
            noise,
            thr,
            seed,
            i,
        )
        base_rows.append(b)
        gov_rows.append(g)

    def agg(rows):
        return {
            "main_rate": float(np.mean([r["main_ok"] for r in rows])),
            "safe_rate": float(np.mean([r["safe_ok"] for r in rows])),
            "false_conf_rate": float(np.mean([r["false_confidence"] for r in rows])),
            "support_rate": float(np.mean([r["support_rate"] for r in rows])),
            "abstain_rate": float(np.mean([r["abstained"] for r in rows])),
            "loop_steps_mean": float(np.mean([r["loop_steps"] for r in rows])),
        }

    return {
        "mode": mode,
        "seed": seed,
        "note": note,
        "baseline": agg(base_rows),
        "governor": agg(gov_rows),
        "lift_main": float(
            np.mean([r["main_ok"] for r in gov_rows])
            - np.mean([r["main_ok"] for r in base_rows])
        ),
    }


def main() -> int:
    modes = ["poison", "conflict", "multi_hop", "stampede"]
    print("=" * 70)
    print(" LOGIC-LOOP ADVERSARIAL — poison · conflict · multi-hop · stampede")
    print("=" * 70)

    all_eps = []
    by_mode: dict[str, list] = {m: [] for m in modes}

    for mode in modes:
        print(f"\n── mode={mode} ──")
        for seed in SEEDS:
            ep = run_mode(mode, seed)
            all_eps.append(ep)
            by_mode[mode].append(ep)
            g, b = ep["governor"], ep["baseline"]
            print(
                f"  seed={seed}  base MAIN={b['main_rate']:.3f} SAFE={b['safe_rate']:.3f} FC={b['false_conf_rate']:.3f}  "
                f"gov MAIN={g['main_rate']:.3f} SAFE={g['safe_rate']:.3f} FC={g['false_conf_rate']:.3f} "
                f"abs={g['abstain_rate']:.3f}  lift={ep['lift_main']:+.3f}"
            )

    # summary per mode
    mode_summary = {}
    for mode, eps in by_mode.items():
        mode_summary[mode] = {
            "baseline_main": float(np.mean([e["baseline"]["main_rate"] for e in eps])),
            "governor_main": float(np.mean([e["governor"]["main_rate"] for e in eps])),
            "baseline_safe": float(np.mean([e["baseline"]["safe_rate"] for e in eps])),
            "governor_safe": float(np.mean([e["governor"]["safe_rate"] for e in eps])),
            "baseline_fc": float(np.mean([e["baseline"]["false_conf_rate"] for e in eps])),
            "governor_fc": float(np.mean([e["governor"]["false_conf_rate"] for e in eps])),
            "governor_abstain": float(np.mean([e["governor"]["abstain_rate"] for e in eps])),
            "lift_main": float(np.mean([e["lift_main"] for e in eps])),
        }

    overall_lift = float(np.mean([e["lift_main"] for e in all_eps]))
    overall_gov_main = float(np.mean([e["governor"]["main_rate"] for e in all_eps]))
    overall_gov_safe = float(np.mean([e["governor"]["safe_rate"] for e in all_eps]))
    overall_gov_fc = float(np.mean([e["governor"]["false_conf_rate"] for e in all_eps]))
    overall_base_main = float(np.mean([e["baseline"]["main_rate"] for e in all_eps]))

    # pass: mean across modes
    pass_main = overall_gov_main >= MAIN_MIN
    pass_safe = overall_gov_safe >= SAFE_MIN
    pass_fc = overall_gov_fc <= FC_MAX
    pass_lift = overall_lift >= LIFT_MAIN_MIN
    # poison+conflict should show abstain or high safe
    hard_modes = ["poison", "conflict", "multi_hop"]
    hard_safe = float(np.mean([mode_summary[m]["governor_safe"] for m in hard_modes]))
    pass_hard = hard_safe >= 0.80
    pass_all = pass_main and pass_safe and pass_fc and pass_lift and pass_hard

    # plot
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(modes))
    bm = [mode_summary[m]["baseline_main"] for m in modes]
    gm = [mode_summary[m]["governor_main"] for m in modes]
    gs = [mode_summary[m]["governor_safe"] for m in modes]
    ax.bar(x - 0.25, bm, 0.25, label="base MAIN", color="#ff8a8a")
    ax.bar(x, gm, 0.25, label="gov MAIN", color="#5dffb0")
    ax.bar(x + 0.25, gs, 0.25, label="gov SAFE", color="#6eb6ff")
    ax.set_xticks(x)
    ax.set_xticklabels(modes)
    ax.set_ylim(0, 1.05)
    ax.set_title(
        f"Adversarial logic-loop  lift_main={overall_lift:+.2f}  "
        f"{'PASS' if pass_all else 'fail'}"
    )
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(OUT / "logic_loop_adversarial.png", dpi=140)
    plt.close(fig)

    payload = {
        "proto": "logic_loop_adversarial_v1",
        "modes": modes,
        "seeds": SEEDS,
        "items_per_mode": ITEMS_PER_MODE,
        "bars": {
            "main_min": MAIN_MIN,
            "safe_min": SAFE_MIN,
            "fc_max": FC_MAX,
            "lift_main_min": LIFT_MAIN_MIN,
        },
        "mode_summary": mode_summary,
        "overall": {
            "baseline_main": overall_base_main,
            "governor_main": overall_gov_main,
            "governor_safe": overall_gov_safe,
            "governor_fc": overall_gov_fc,
            "lift_main": overall_lift,
        },
        "pass_all": pass_all,
        "pass_flags": {
            "main": pass_main,
            "safe": pass_safe,
            "fc": pass_fc,
            "lift": pass_lift,
            "hard_safe": pass_hard,
        },
    }
    (OUT / "logic_loop_adversarial_results.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Logic-loop adversarial exam",
        "",
        f"**Pass:** {'YES' if pass_all else 'NO'}",
        "",
        "| Mode | base MAIN | gov MAIN | gov SAFE | gov FC | lift MAIN |",
        "|------|----------:|---------:|---------:|-------:|----------:|",
    ]
    for m in modes:
        s = mode_summary[m]
        lines.append(
            f"| {m} | {s['baseline_main']:.3f} | {s['governor_main']:.3f} | "
            f"{s['governor_safe']:.3f} | {s['governor_fc']:.3f} | {s['lift_main']:+.3f} |"
        )
    lines.extend(
        [
            "",
            f"**Overall lift MAIN:** {overall_lift:+.3f}",
            f"**Overall gov SAFE:** {overall_gov_safe:.3f} · FC {overall_gov_fc:.3f}",
            "",
            "Plot: `logic_loop_adversarial.png`",
        ]
    )
    (OUT / "LOGIC_LOOP_ADVERSARIAL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(" SUMMARY")
    for m in modes:
        s = mode_summary[m]
        print(
            f"  {m:12s}  lift={s['lift_main']:+.3f}  govMAIN={s['governor_main']:.3f}  "
            f"SAFE={s['governor_safe']:.3f}  FC={s['governor_fc']:.3f}"
        )
    print(
        f"  OVERALL lift={overall_lift:+.3f}  "
        f"{'PASS' if pass_all else 'fail'}  "
        f"(M={pass_main} S={pass_safe} FC={pass_fc} L={pass_lift} H={pass_hard})"
    )
    print(f"  → {OUT / 'LOGIC_LOOP_ADVERSARIAL.md'}")
    print("=" * 70)
    return 0 if pass_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
