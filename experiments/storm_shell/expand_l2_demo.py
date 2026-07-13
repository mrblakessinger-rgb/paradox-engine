"""
Expand-L2 flexibility prototype (defense / mid-band flex)
==========================================================
L2 = mid performance band. Baseline treats it as passive bulk.
Expand-L2 makes the mid band *do work* under interference:

  1) Adaptive band width — L2 grows under high I (more agents get mid flex)
  2) Mid-band instinct flex — high I → damper/repair up, explore moderated
     calm I → slight explore room so L2 doesn't crystallize
  3) Soft absorb — strongest L2 gently lifts weakest L3 (edge → mid),
     capped so we never force lock at 1.0

DNA: PROMOTED (frozen). No promote path here — metrics only.

  python real_world/expand_l2_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

def _find_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(6):
        if (p / 'KERNEL_v1.py').exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[2]

ROOT = _find_root()
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = 0.92
CEILING = K.CEILING_SOFT


def assign_tiers(
    agents: list,
    *,
    bottom_frac: float = 0.20,
    top_frac: float = 0.20,
) -> dict[int, int]:
    """L1 top · L2 mid · L3 bottom by performance."""
    n = len(agents)
    order = np.argsort([a.performance for a in agents])  # low → high
    n3 = max(1, int(round(n * bottom_frac)))
    n1 = max(1, int(round(n * top_frac)))
    l3 = set(int(i) for i in order[:n3])
    l1 = set(int(i) for i in order[-n1:])
    tiers: dict[int, int] = {}
    for i in range(n):
        if i in l1:
            tiers[i] = 1
        elif i in l3:
            tiers[i] = 3
        else:
            tiers[i] = 2
    return tiers


def adaptive_band_fracs(interference: float) -> tuple[float, float]:
    """
    Under high I, shrink elite/struggling labels slightly so more agents
    sit in L2 and receive mid-band flex (expand L2).
    """
    # baseline 20/20 → under storm 12/12 (L2 ~76%)
    if interference >= 2.6:
        return 0.12, 0.12
    if interference >= 2.0:
        return 0.15, 0.15
    if interference >= 1.4:
        return 0.18, 0.18
    return 0.20, 0.20


def flex_l2_instincts(
    agents: list,
    tiers: dict[int, int],
    interference: float,
    *,
    enabled: bool,
) -> None:
    """Episode-local instinct nudge for L2 only. Does not touch DNA."""
    if not enabled:
        return
    high_i = interference >= 2.0
    storm = interference >= 2.5
    for i, a in enumerate(agents):
        if tiers.get(i) != 2:
            continue
        inst = a.instinct
        if high_i:
            # Hold the middle: damp surge, repair toward target
            inst["damper_bias"] = float(np.clip(inst.get("damper_bias", 1.0) * 1.04, 0.3, 2.4))
            inst["repair_bias"] = float(np.clip(inst.get("repair_bias", 1.0) * 1.03, 0.3, 2.4))
            inst["viscosity_bias"] = float(np.clip(inst.get("viscosity_bias", 1.0) * 1.02, 0.3, 2.4))
            # Don't freeze explore entirely — L2 flexibility means some mobility
            exp = float(inst.get("explore_bias", 0.3))
            if storm:
                inst["explore_bias"] = float(np.clip(exp * 0.97 + 0.01, 0.05, 0.55))
            else:
                inst["explore_bias"] = float(np.clip(exp * 0.99 + 0.015, 0.05, 0.55))
        else:
            # Calm: slight explore room so mid band doesn't crystallize
            inst["explore_bias"] = float(
                np.clip(inst.get("explore_bias", 0.3) * 1.01 + 0.005, 0.05, 0.55)
            )


def soft_absorb_edge(
    agents: list,
    tiers: dict[int, int],
    interference: float,
    rng: np.random.Generator,
    *,
    enabled: bool,
    max_pairs: int = 2,
) -> int:
    """
    Strongest L2 gently lifts weakest L3 (edge → toward mid/core band).
    Returns number of absorb pairs applied.
    """
    if not enabled or interference < 1.8:
        return 0
    l2 = [i for i, t in tiers.items() if t == 2]
    l3 = [i for i, t in tiers.items() if t == 3]
    if not l2 or not l3:
        return 0
    l2_sorted = sorted(l2, key=lambda i: agents[i].performance, reverse=True)
    l3_sorted = sorted(l3, key=lambda i: agents[i].performance)  # weakest first
    n = min(max_pairs, len(l2_sorted), len(l3_sorted))
    # more absorb under storm
    if interference >= 2.5:
        n = min(n + 1, len(l2_sorted), len(l3_sorted), 4)
    done = 0
    for k in range(n):
        mid_i = l2_sorted[k]
        edge_i = l3_sorted[k]
        a, b = agents[mid_i], agents[edge_i]
        # pull edge toward mid coherence (capped)
        pull = 0.12 + 0.04 * min(1.0, (interference - 1.8) / 1.2)
        b.coherence = float(
            np.clip(0.72 * b.coherence + pull * a.coherence + 0.03, 0.0, CEILING)
        )
        b.flux = float(np.clip(b.flux * 0.88, -2.5, 2.5))
        b.velocity *= 0.9
        # mid shares a little repair instinct (not full hive rewrite)
        for key in ("repair_bias", "damper_bias"):
            vb, va = b.instinct.get(key, 1.0), a.instinct.get(key, 1.0)
            b.instinct[key] = float(0.85 * vb + 0.15 * va)
        done += 1
    return done


def schedule_I(
    t: int,
    steps: int,
    rng: np.random.Generator,
    *,
    mode: str,
    I: float,
) -> float:
    """
    normal  — mild variable walk (promoted DNA already wins → neutral L2 signal)
    cruel   — long high-I plateaus so edge actually frays (stress test for expand-L2)
    """
    if mode == "cruel":
        # 0–15 warm, 15–55 hell, 55–75 thrash, 75–end mixed recovery storms
        if t < 15:
            return float(np.clip(1.2 + rng.normal(0, 0.05), 0.8, 1.6))
        if t < 55:
            return float(np.clip(2.85 + rng.normal(0, 0.06), 2.5, 3.0))
        if t < 75:
            return float(rng.choice([2.4, 2.7, 2.9, 3.0]))
        if rng.random() < 0.25:
            return float(rng.choice([2.2, 2.6, 2.9]))
        return float(np.clip(I + rng.normal(0, 0.1), 1.0, 2.8))
    # normal
    if rng.random() < 0.10:
        return float(rng.choice([0.8, 1.4, 2.0, 2.6, 2.9]))
    return float(np.clip(I + rng.normal(0, 0.08), 0.6, 3.0))


def run_episode(
    *,
    seed: int,
    steps: int = 100,
    expand_l2: bool = False,
    target: float = TARGET,
    mode: str = "cruel",
) -> dict:
    rng = np.random.default_rng(seed)
    agents = K.make_swarm(rng)
    # Cruel mode: start more spread / weaker so edge can fail without DNA change
    if mode == "cruel":
        for a in agents:
            a.coherence = float(np.clip(a.coherence * 0.92 + rng.uniform(-0.05, 0.02), 0.25, 0.72))
            a.flux = float(a.flux + rng.normal(0, 0.25))
    dna = dict(K.PROMOTED_DNA)
    # honor contract target; do not mutate promoted source permanently
    dna = {
        **dna,
        "intuition": {**dna["intuition"], "target_coherence": float(target)},
    }
    paradox = K.Paradox(dna)
    paradox.install_drivers(agents)

    stab_series: list[float] = []
    l2_frac_series: list[float] = []
    l3_mean_coh_series: list[float] = []
    l2_mean_coh_series: list[float] = []
    absorb_total = 0
    ambient = 0.0
    I = 1.6

    for t in range(steps):
        I = schedule_I(t, steps, rng, mode=mode, I=I)

        for a in agents:
            a.step(I, ambient, rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))

        for a in agents:
            tc = a.instinct.get("target_coherence", target)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )

        if expand_l2:
            bot_f, top_f = adaptive_band_fracs(I)
        else:
            bot_f, top_f = 0.20, 0.20

        tiers = assign_tiers(agents, bottom_frac=bot_f, top_frac=top_f)
        flex_l2_instincts(agents, tiers, I, enabled=expand_l2)
        absorb_total += soft_absorb_edge(
            agents, tiers, I, rng, enabled=expand_l2, max_pairs=2
        )

        paradox.hive_pair_churn(agents, rng)
        paradox.install_drivers(agents)

        # re-tier after hive for metrics snapshot
        tiers = assign_tiers(agents, bottom_frac=bot_f, top_frac=top_f)
        n = len(agents)
        n2 = sum(1 for t_ in tiers.values() if t_ == 2)
        l3_ids = [i for i, t_ in tiers.items() if t_ == 3]
        l2_ids = [i for i, t_ in tiers.items() if t_ == 2]

        stab_series.append(K.stability(agents))
        l2_frac_series.append(n2 / max(n, 1))
        l3_mean_coh_series.append(
            float(np.mean([agents[i].coherence for i in l3_ids])) if l3_ids else 0.0
        )
        l2_mean_coh_series.append(
            float(np.mean([agents[i].coherence for i in l2_ids])) if l2_ids else 0.0
        )

    arr = np.array(stab_series)
    late_n = max(1, steps // 5)
    final_tiers = assign_tiers(agents)
    counts = {1: 0, 2: 0, 3: 0}
    for t_ in final_tiers.values():
        counts[t_] += 1

    # edge health: mean coherence of bottom 20%
    order = np.argsort([a.performance for a in agents])
    edge = [agents[int(i)] for i in order[: max(1, int(0.2 * len(agents)))]]
    edge_coh = float(np.mean([a.coherence for a in edge]))

    # hell-window metrics (steps 15–55 in cruel mode)
    hell = arr[15:55] if len(arr) > 55 else arr
    return {
        "seed": seed,
        "expand_l2": expand_l2,
        "mode": mode,
        "target": target,
        "mean_stab": float(np.mean(arr)),
        "late_stab": float(np.mean(arr[-late_n:])),
        "min_stab": float(np.min(arr)),
        "max_stab": float(np.max(arr)),
        "hell_mean": float(np.mean(hell)),
        "hell_min": float(np.min(hell)),
        "locked_frac": float(np.mean(arr >= CEILING)),
        "tier_L1": counts[1],
        "tier_L2": counts[2],
        "tier_L3": counts[3],
        "mean_l2_frac": float(np.mean(l2_frac_series)),
        "late_l3_coh": float(np.mean(l3_mean_coh_series[-late_n:])),
        "late_l2_coh": float(np.mean(l2_mean_coh_series[-late_n:])),
        "edge_coh_final": edge_coh,
        "absorb_total": int(absorb_total),
        "stab_series": stab_series,
        "l2_frac_series": l2_frac_series,
        "l3_mean_coh_series": l3_mean_coh_series,
    }


def multi_seed(seeds: list[int], steps: int = 100, mode: str = "cruel") -> dict:
    rows = []
    for expand in (False, True):
        for seed in seeds:
            r = run_episode(seed=seed, steps=steps, expand_l2=expand, mode=mode)
            rows.append(r)
            tag = "EXPAND-L2" if expand else "BASELINE "
            print(
                f"  {tag} seed={seed:3d}  late={r['late_stab']:.4f}  "
                f"hell_min={r['hell_min']:.4f}  edge_coh={r['edge_coh_final']:.3f}  "
                f"L2%={r['mean_l2_frac']*100:.0f}  absorb={r['absorb_total']}"
            )
    return {"rows": rows}


def summarize(rows: list[dict], expand: bool) -> dict:
    rs = [r for r in rows if r["expand_l2"] is expand]
    return {
        "n": len(rs),
        "late_mean": float(np.mean([r["late_stab"] for r in rs])),
        "late_std": float(np.std([r["late_stab"] for r in rs])),
        "min_mean": float(np.mean([r["min_stab"] for r in rs])),
        "hell_mean": float(np.mean([r["hell_mean"] for r in rs])),
        "hell_min_mean": float(np.mean([r["hell_min"] for r in rs])),
        "edge_coh_mean": float(np.mean([r["edge_coh_final"] for r in rs])),
        "l2_frac_mean": float(np.mean([r["mean_l2_frac"] for r in rs])),
        "locked_mean": float(np.mean([r["locked_frac"] for r in rs])),
        "absorb_mean": float(np.mean([r["absorb_total"] for r in rs])),
    }


def main() -> int:
    print("=" * 64)
    print(" EXPAND-L2 FLEXIBILITY PROTOTYPE")
    print(" mid-band adaptive width + instinct flex + soft edge absorb")
    print(" DNA: PROMOTED (frozen) · no promote · mode=cruel (edge stress)")
    print("=" * 64)

    seeds = [7, 11, 21, 42, 99]
    steps = 100
    mode = "cruel"
    print(f"\n[1] Multi-seed baseline vs expand-L2 ({len(seeds)} seeds × {steps} steps, {mode})")
    cmp_ = multi_seed(seeds, steps=steps, mode=mode)
    base = summarize(cmp_["rows"], False)
    exp = summarize(cmp_["rows"], True)

    print("\n[2] SUMMARY")
    print(
        f"  BASELINE  late={base['late_mean']:.4f}±{base['late_std']:.4f}  "
        f"hell_min={base['hell_min_mean']:.4f}  edge_coh={base['edge_coh_mean']:.3f}  "
        f"L2%={base['l2_frac_mean']*100:.0f}  lock={base['locked_mean']:.3f}"
    )
    print(
        f"  EXPAND-L2 late={exp['late_mean']:.4f}±{exp['late_std']:.4f}  "
        f"hell_min={exp['hell_min_mean']:.4f}  edge_coh={exp['edge_coh_mean']:.3f}  "
        f"L2%={exp['l2_frac_mean']*100:.0f}  lock={exp['locked_mean']:.3f}  "
        f"absorb/ep≈{exp['absorb_mean']:.0f}"
    )
    d_late = exp["late_mean"] - base["late_mean"]
    d_edge = exp["edge_coh_mean"] - base["edge_coh_mean"]
    d_min = exp["min_mean"] - base["min_mean"]
    d_hell = exp["hell_min_mean"] - base["hell_min_mean"]
    print(
        f"  Δ late_stab = {d_late:+.4f}  Δ edge_coh = {d_edge:+.3f}  "
        f"Δ min_stab = {d_min:+.4f}  Δ hell_min = {d_hell:+.4f}"
    )

    # Plot seed=42 pair for visual
    b42 = run_episode(seed=42, steps=120, expand_l2=False, mode=mode)
    e42 = run_episode(seed=42, steps=120, expand_l2=True, mode=mode)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    ax = axes[0]
    ax.plot(b42["stab_series"], label="baseline", color="#888", lw=1.5)
    ax.plot(e42["stab_series"], label="expand-L2", color="#2ecc71", lw=1.8)
    ax.axhline(TARGET, color="#3498db", ls="--", lw=1, label=f"target {TARGET}")
    ax.axhline(CEILING, color="#e74c3c", ls=":", lw=1, label=f"soft ceiling {CEILING}")
    ax.axvspan(15, 55, color="#e74c3c", alpha=0.08, label="hell window")
    ax.set_ylabel("stability")
    ax.set_title("Expand-L2 vs baseline (seed=42, cruel I, promoted DNA frozen)")
    ax.legend(loc="lower right", fontsize=8)
    ax.set_ylim(0.45, 1.02)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(b42["l3_mean_coh_series"], label="baseline L3 mean coh", color="#888", lw=1.5)
    ax2.plot(e42["l3_mean_coh_series"], label="expand-L2 L3 mean coh", color="#e67e22", lw=1.8)
    ax2.plot(e42["l2_frac_series"], label="expand-L2 L2 fraction", color="#9b59b6", lw=1.2, alpha=0.8)
    ax2.set_xlabel("step")
    ax2.set_ylabel("coh / L2 frac")
    ax2.legend(loc="lower right", fontsize=8)
    ax2.grid(True, alpha=0.25)
    fig.tight_layout()
    png = OUT / "expand_l2_comparison.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "proto": "expand_l2_v1",
        "dna": "PROMOTED_FROZEN",
        "mode": mode,
        "target": TARGET,
        "seeds": seeds,
        "steps": steps,
        "baseline": base,
        "expand_l2": exp,
        "delta": {
            "late_stab": d_late,
            "edge_coh": d_edge,
            "min_stab": d_min,
            "hell_min": d_hell,
        },
        "mechanics": [
            "adaptive L2 band width under high I",
            "L2-only damper/repair/explore flex",
            "soft absorb: strong L2 lifts weak L3 (capped, anti-lock)",
            "cruel schedule: long high-I plateau so edge can fray",
        ],
        "note": "Prototype only — not promoted into Soft Pack DNA",
    }
    js = OUT / "expand_l2_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")

    ok_late = d_late >= -0.02
    ok_lock = exp["locked_mean"] <= base["locked_mean"] + 0.02
    improved = (
        d_edge > 0.01 or d_min > 0.01 or d_late > 0.005 or d_hell > 0.01
    ) and ok_late and ok_lock
    print("\n[3] PROTOTYPE SIGNAL")
    if improved:
        print("  → Expand-L2 shows useful lift (edge/min/late/hell) without lock blowup.")
    elif ok_late and ok_lock:
        print("  → Neutral / small effect — keep for beacon stack; retune knobs later.")
    else:
        print("  → Regression risk — review before stacking beacons.")

    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
