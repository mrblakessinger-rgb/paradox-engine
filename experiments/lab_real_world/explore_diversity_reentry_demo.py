"""
Controlled explore diversity + absolute-band risk re-entry
==========================================================
- Spread explore_bias across swarm (not homogenized to one value)
- Re-enter only agents in ABSOLUTE hurt band (coh < 0.88), not percentile L3
- Optional: prefer re-entry for high-explore "risk" profiles among the hurt

  python real_world/explore_diversity_reentry_demo.py
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

import KERNEL_v1 as K

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
REFLECTED = ROOT / "KERNEL_v1_dna_reflected.json"

HURT_COH = 0.88
STRONG_COH = 0.94
SEEDS = [7, 11, 42, 99]
STEPS = 120


def load_dna() -> dict:
    if REFLECTED.exists():
        return json.loads(REFLECTED.read_text(encoding="utf-8"))
    return dict(K.PROMOTED_DNA)


def install_with_explore_diversity(
    paradox: K.Paradox,
    agents: list,
    rng: np.random.Generator,
    *,
    diversity: bool,
) -> None:
    """Install DNA instincts; pin a personal explore identity so risk caste can exist."""
    paradox.install_drivers(agents)
    if not diversity:
        for a in agents:
            a._explore_id = float(a.instinct.get("explore_bias", 0.12))  # type: ignore
            a._risk_id = float(a.instinct.get("risk_aversion", 0.5))  # type: ignore
        return
    n = len(agents)
    base = float(paradox.intuition.get("explore_bias", 0.12))
    # Shuffle ranks so identity isn't correlated with agent id geometry only
    ranks = np.arange(n)
    rng.shuffle(ranks)
    for i, a in enumerate(agents):
        u = float(ranks[i]) / max(1, n - 1)
        # Wide controlled band: cautious → risk-taker
        explore_id = float(np.clip(0.05 + 0.38 * u, 0.05, 0.43))
        # slight pull toward DNA base so not pure noise
        explore_id = float(np.clip(0.25 * base + 0.75 * explore_id, 0.05, 0.43))
        risk_id = float(np.clip(0.92 - 0.60 * u, 0.22, 0.92))
        a._explore_id = explore_id  # type: ignore
        a._risk_id = risk_id  # type: ignore
        a.instinct["explore_bias"] = explore_id
        a.instinct["risk_aversion"] = risk_id


def reapply_explore_identity(agents: list) -> None:
    """After install_drivers flattens instincts, restore personal explore/risk ids."""
    for a in agents:
        if hasattr(a, "_explore_id"):
            a.instinct["explore_bias"] = float(a._explore_id)
        if hasattr(a, "_risk_id"):
            a.instinct["risk_aversion"] = float(a._risk_id)


def absolute_bands(agents: list) -> dict:
    hurt = [i for i, a in enumerate(agents) if a.coherence < HURT_COH]
    mid = [i for i, a in enumerate(agents) if HURT_COH <= a.coherence < STRONG_COH]
    strong = [i for i, a in enumerate(agents) if a.coherence >= STRONG_COH]
    softlock = [i for i, a in enumerate(agents) if a.coherence >= K.CEILING_SOFT]
    return {
        "hurt": hurt,
        "mid": mid,
        "strong": strong,
        "softlock": softlock,
        "n_hurt": len(hurt),
        "n_mid": len(mid),
        "n_strong": len(strong),
        "n_softlock": len(softlock),
    }


def risk_among(agents: list, idxs: list[int]) -> list[int]:
    if not idxs:
        return []
    ex = np.array([float(agents[i].instinct.get("explore_bias", 0.1)) for i in idxs])
    # top half of explore within the hurt set, or above global median
    all_ex = np.array([float(a.instinct.get("explore_bias", 0.1)) for a in agents])
    med = float(np.median(all_ex))
    out = []
    for i, e in zip(idxs, ex):
        if e >= med:
            out.append(i)
    return out


def reenter_hurt_risk_takers(agents: list, paradox: K.Paradox, rng: np.random.Generator) -> int:
    """Only absolute hurt band; prefer risk (high explore) among them."""
    bands = absolute_bands(agents)
    hurt = bands["hurt"]
    if not hurt:
        return 0
    risks = risk_among(agents, hurt)
    # If no high-explore in hurt, still lift worst 30% of hurt (not whole percentile L3)
    targets = risks if risks else sorted(hurt, key=lambda i: agents[i].coherence)[: max(1, len(hurt) // 3)]
    floor = float(paradox.intuition.get("floor_boost", 0.04))
    n = 0
    for i in targets:
        a = agents[i]
        a.coherence = float(np.clip(a.coherence + 0.05 + 0.8 * floor, 0, K.CEILING_SOFT - 0.01))
        # encourage re-entry without turning everyone into maniacs
        a.instinct["explore_bias"] = float(
            np.clip(a.instinct.get("explore_bias", 0.15) * 0.85 + 0.08, 0.05, 0.42)
        )
        a.instinct["risk_aversion"] = float(
            np.clip(a.instinct.get("risk_aversion", 0.5) * 0.94, 0.22, 0.92)
        )
        a.instinct["repair_bias"] = float(
            np.clip(a.instinct.get("repair_bias", 1.0) + 0.05, 0.5, 2.3)
        )
        if hasattr(a, "_explore_id"):
            a._explore_id = float(a.instinct["explore_bias"])
        if hasattr(a, "_risk_id"):
            a._risk_id = float(a.instinct["risk_aversion"])
        n += 1
    return n


def run_episode(
    *,
    seed: int,
    diversity: bool,
    reentry: bool,
    steps: int = STEPS,
) -> dict:
    rng = np.random.default_rng(seed)
    dna = load_dna()
    agents = K.make_swarm(rng)
    paradox = K.Paradox(dna)
    paradox.load_dna(dna)
    paradox.intuition["target_coherence"] = K.TARGET_STABILITY
    install_with_explore_diversity(paradox, agents, rng, diversity=diversity)

    ambient = 0.0
    I = 1.65
    series = []
    reentry_events = 0
    hurt_series = []
    explore_std_series = []

    for t in range(steps):
        if rng.random() < 0.11:
            I = float(rng.choice([0.7, 1.3, 1.9, 2.5, 2.95]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.085), 0.55, 3.0))

        for a in agents:
            a.step(I, ambient, rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))

        for a in agents:
            tc = a.instinct.get("target_coherence", K.TARGET_STABILITY)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )

        # hive
        paradox.hive_pair_churn(agents, rng)
        paradox.install_drivers(agents)
        # install_drivers homogenizes — pin explore/risk identity back (diversity mode)
        if diversity:
            reapply_explore_identity(agents)

        # Re-entry only when swarm is stable enough (don't reopen into freefall)
        stab = K.stability(agents)
        if reentry and t > 5 and t % 6 == 0 and stab >= K.TARGET_STABILITY - 0.05:
            n_re = reenter_hurt_risk_takers(agents, paradox, rng)
            reentry_events += n_re
            # Reentry may nudge explore — update identity anchors for those agents
            if diversity and n_re:
                for a in agents:
                    if a.coherence < HURT_COH + 0.05:
                        a._explore_id = float(a.instinct.get("explore_bias", getattr(a, "_explore_id", 0.12)))
                        a._risk_id = float(a.instinct.get("risk_aversion", getattr(a, "_risk_id", 0.5)))

        bands = absolute_bands(agents)
        hurt_series.append(bands["n_hurt"])
        explore_std_series.append(float(np.std([a.instinct.get("explore_bias", 0.1) for a in agents])))
        series.append(stab)

    arr = np.array(series, float)
    late_n = max(1, steps // 5)
    bands = absolute_bands(agents)
    explores = np.array([float(a.instinct.get("explore_bias", 0.1)) for a in agents])
    hurt_risk = risk_among(agents, bands["hurt"])

    return {
        "seed": seed,
        "diversity": diversity,
        "reentry": reentry,
        "late_stab": float(np.mean(arr[-late_n:])),
        "mean_stab": float(np.mean(arr)),
        "min_stab": float(np.min(arr)),
        "locked_frac": float(np.mean(arr >= K.CEILING_SOFT)),
        "n_hurt": bands["n_hurt"],
        "n_mid": bands["n_mid"],
        "n_strong": bands["n_strong"],
        "n_softlock": bands["n_softlock"],
        "hurt_risk_takers": len(hurt_risk),
        "explore_mean": float(np.mean(explores)),
        "explore_std": float(np.std(explores)),
        "explore_min": float(np.min(explores)),
        "explore_max": float(np.max(explores)),
        "reentry_events": reentry_events,
        "mean_hurt_count": float(np.mean(hurt_series)),
        "final_hurt_series": hurt_series,
        "stab_series": series,
        "explore_std_series": explore_std_series,
    }


def main() -> int:
    print("=" * 64)
    print(" EXPLORE DIVERSITY + ABSOLUTE-BAND RE-ENTRY")
    print(f" Hurt band: coh < {HURT_COH}  |  reentry if stab >= {K.TARGET_STABILITY - 0.05:.2f}")
    print("=" * 64)

    configs = [
        ("baseline_flat", dict(diversity=False, reentry=False)),
        ("diversity_only", dict(diversity=True, reentry=False)),
        ("diversity_reentry", dict(diversity=True, reentry=True)),
    ]

    all_rows = []
    for name, kw in configs:
        print(f"\n[{name}]")
        seed_rows = []
        for seed in SEEDS:
            r = run_episode(seed=seed, **kw)
            r["config"] = name
            seed_rows.append(r)
            all_rows.append(r)
            print(
                f"  seed={seed}  late={r['late_stab']:.4f}  hurt={r['n_hurt']}  "
                f"strong={r['n_strong']}  explore_std={r['explore_std']:.3f}  "
                f"hurt_risk={r['hurt_risk_takers']}  reentries={r['reentry_events']}"
            )
        print(
            f"  MEAN late={np.mean([x['late_stab'] for x in seed_rows]):.4f}  "
            f"hurt={np.mean([x['n_hurt'] for x in seed_rows]):.1f}  "
            f"explore_std={np.mean([x['explore_std'] for x in seed_rows]):.3f}"
        )

    # Seed 42 detail plot
    detail = {}
    for name, kw in configs:
        detail[name] = run_episode(seed=42, steps=STEPS, **kw)

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    colors = {"baseline_flat": "#ff6b8a", "diversity_only": "#ffd060", "diversity_reentry": "#5dffb0"}
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    for name, r in detail.items():
        ax.plot(r["stab_series"], color=colors[name], label=name)
    ax.axhline(0.92, color="#7ec8ff", ls="--", alpha=0.6)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Stability", color="white")
    ax.set_title("Explore diversity + absolute-band reentry (seed 42)", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    for name, r in detail.items():
        ax.plot(r["final_hurt_series"], color=colors[name], label=f"{name} n_hurt")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    ax.set_ylabel("# hurt (coh<0.88)", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "explore_diversity_reentry.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    # Summary table
    summary = {}
    for name, _ in configs:
        rs = [x for x in all_rows if x["config"] == name]
        summary[name] = {
            "late_mean": float(np.mean([x["late_stab"] for x in rs])),
            "hurt_mean": float(np.mean([x["n_hurt"] for x in rs])),
            "strong_mean": float(np.mean([x["n_strong"] for x in rs])),
            "explore_std_mean": float(np.mean([x["explore_std"] for x in rs])),
            "reentry_events_mean": float(np.mean([x["reentry_events"] for x in rs])),
            "lock_mean": float(np.mean([x["locked_frac"] for x in rs])),
        }

    best = max(summary.items(), key=lambda kv: (kv[1]["late_mean"], -kv[1]["hurt_mean"]))
    report = {
        "hurt_threshold": HURT_COH,
        "summary": summary,
        "recommended_config": best[0],
        "seed42_detail": {
            k: {kk: vv for kk, vv in v.items() if kk not in ("stab_series", "final_hurt_series", "explore_std_series")}
            for k, v in detail.items()
        },
        "doctrine": {
            "percentile_L3": "ignored for reentry",
            "absolute_hurt": f"coh < {HURT_COH}",
            "risk": "high explore among hurt",
            "gate": "only reenter if swarm stab >= target-0.05",
        },
    }
    (OUT / "explore_diversity_reentry.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n" + "=" * 64)
    print(" SUMMARY (mean over seeds)")
    print("=" * 64)
    for name, s in summary.items():
        print(
            f"  {name:20s}  late={s['late_mean']:.4f}  hurt={s['hurt_mean']:.1f}  "
            f"strong={s['strong_mean']:.1f}  exp_std={s['explore_std_mean']:.3f}  "
            f"reentries={s['reentry_events_mean']:.1f}"
        )
    print(f"\n  Recommended: {best[0]}")
    print(f"  Plot → {OUT / 'explore_diversity_reentry.png'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
