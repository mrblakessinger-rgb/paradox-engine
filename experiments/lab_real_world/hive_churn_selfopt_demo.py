"""
Hive churn self-optimize + tier census + risk re-entry probe
============================================================
1) Multi-seed: PROMOTED DNA vs Paradox-reflected DNA (does reflection help?)
2) Fixed PAIR_FRAC=5% vs self-optimizing churn (predictive + real-time)
3) End-of-run tier census: L1 elite / L2 mid / L3 struggling
4) Risk-taker re-entry: boost explore-heavy agents stuck in L3?

Target outer actuate not used here — pure KERNEL hive dynamics.
Actuate target philosophy held: desire band ~0.92–0.925 via DNA target_coherence.

  python real_world/hive_churn_selfopt_demo.py
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
DNA_REFLECTED = ROOT / "KERNEL_v1_dna_reflected.json"

# Churn bounds for self-opt (never free-for-all)
PAIR_LO, PAIR_HI = 0.02, 0.12
PAIR_DEFAULT = 0.05


def load_dna(kind: str) -> dict:
    if kind == "promoted":
        return dict(K.PROMOTED_DNA)
    if kind == "reflected":
        if not DNA_REFLECTED.exists():
            raise FileNotFoundError(f"Missing {DNA_REFLECTED} — run paradox_reflect first")
        return json.loads(DNA_REFLECTED.read_text(encoding="utf-8"))
    raise ValueError(kind)


def assign_tiers(agents: list, *, bottom_frac: float = 0.20, top_frac: float = 0.20) -> dict:
    """
    L1 = top performance (elites / risk-capable high performers)
    L2 = mid
    L3 = bottom (struggling / crashed band)
    """
    n = len(agents)
    order = np.argsort([a.performance for a in agents])  # low → high
    n3 = max(1, int(round(n * bottom_frac)))
    n1 = max(1, int(round(n * top_frac)))
    l3_idx = set(int(i) for i in order[:n3])
    l1_idx = set(int(i) for i in order[-n1:])
    tiers = {}
    for i, a in enumerate(agents):
        if i in l1_idx:
            tiers[i] = 1
        elif i in l3_idx:
            tiers[i] = 3
        else:
            tiers[i] = 2
    return tiers


def risk_taker_mask(agents: list, tiers: dict) -> list[int]:
    """High explore relative to median, currently in L3."""
    explores = np.array([float(a.instinct.get("explore_bias", 0.3)) for a in agents])
    med = float(np.median(explores))
    out = []
    for i, a in enumerate(agents):
        if tiers.get(i) == 3 and float(a.instinct.get("explore_bias", 0)) >= med * 1.05:
            out.append(i)
    return out


def optimize_pair_frac(
    pair_frac: float,
    *,
    stability: float,
    target: float,
    mean_pred_err: float,
    locked_frac: float,
    d_stab: float,
) -> float:
    """
    Real-time + light predictive self-opt of hive churn rate.
    Predictive: rising pred_error or falling stab → more churn to remix.
    Real-time: far below target → more churn; near target + low lock → less churn (less noise).
    """
    pf = float(pair_frac)
    gap = target - stability

    # Real-time: need lift
    if gap > 0.06:
        pf += 0.008
    elif gap > 0.03:
        pf += 0.004
    elif gap < -0.01 and locked_frac < 0.05:
        # healthy / slightly overshoot — reduce churn noise
        pf -= 0.005

    # Predictive: error rising / stab falling
    if mean_pred_err > 0.12:
        pf += 0.006
    if d_stab < -0.015:
        pf += 0.007
    if d_stab > 0.02 and gap < 0.03:
        pf -= 0.004

    # Anti-lock: if locking, slightly more churn to break crystal
    if locked_frac > 0.08:
        pf += 0.01

    return float(np.clip(pf, PAIR_LO, PAIR_HI))


def run_episode(
    *,
    dna: dict,
    seed: int,
    steps: int = 100,
    self_opt_churn: bool = False,
    risk_reentry: bool = False,
    target: float = 0.92,
) -> dict:
    rng = np.random.default_rng(seed)
    agents = K.make_swarm(rng)
    paradox = K.Paradox(dna)
    # honor DNA target if present but clip sane
    tcoh = float(dna.get("intuition", {}).get("target_coherence", target))
    tcoh = float(np.clip(tcoh, 0.88, 0.94))  # hold band; user likes ~0.925 outer, DNA often 0.92
    if "intuition" in dna:
        dna = dict(dna)
        dna["intuition"] = dict(dna["intuition"])
        dna["intuition"]["target_coherence"] = tcoh
        paradox.load_dna(dna)
    paradox.install_drivers(agents)

    pair_frac = PAIR_DEFAULT
    pair_series = []
    stab_series = []
    ambient = 0.0
    prev_stab = 0.6
    I = 1.6

    # Tag initial explore for risk-taker identity (episode memory on agents — short)
    for a in agents:
        a._risk0 = float(a.instinct.get("explore_bias", 0.3))  # type: ignore

    for t in range(steps):
        # hostile variable I
        if rng.random() < 0.1:
            I = float(rng.choice([0.8, 1.4, 2.0, 2.6, 2.9]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.08), 0.6, 3.0))

        for a in agents:
            a.step(I, ambient, rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))

        # performance for ranking
        for a in agents:
            tc = a.instinct.get("target_coherence", tcoh)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )

        stab = K.stability(agents)
        locked = float(np.mean([a.coherence >= K.CEILING_SOFT for a in agents]))
        mean_pe = float(np.mean([a.pred_error for a in agents]))
        d_stab = stab - prev_stab

        if self_opt_churn:
            pair_frac = optimize_pair_frac(
                pair_frac,
                stability=stab,
                target=tcoh,
                mean_pred_err=mean_pe,
                locked_frac=locked,
                d_stab=d_stab,
            )
            # temporarily monkey-patch churn width via local PAIR override
            old = K.PAIR_FRAC
            K.PAIR_FRAC = pair_frac
            paradox.hive_pair_churn(agents, rng)
            K.PAIR_FRAC = old
        else:
            paradox.hive_pair_churn(agents, rng)

        paradox.install_drivers(agents)

        # Risk re-entry: L3 agents who were risk-takers get floor + explore nudge
        if risk_reentry and t > 0 and t % 8 == 0:
            tiers = assign_tiers(agents)
            risks = risk_taker_mask(agents, tiers)
            for i in risks:
                a = agents[i]
                a.coherence = float(
                    np.clip(a.coherence + 0.04 + 0.5 * paradox.intuition.get("floor_boost", 0.04), 0, K.CEILING_SOFT)
                )
                a.instinct["explore_bias"] = float(
                    np.clip(a.instinct.get("explore_bias", 0.2) * 0.9 + 0.05, 0.05, 0.6)
                )
                # slightly lower risk aversion so they re-enter game, not freeze
                a.instinct["risk_aversion"] = float(
                    np.clip(a.instinct.get("risk_aversion", 0.5) * 0.92, 0.2, 0.95)
                )

        pair_series.append(pair_frac)
        stab_series.append(stab)
        prev_stab = stab

    # Final census
    tiers = assign_tiers(agents)
    counts = {1: 0, 2: 0, 3: 0}
    for i in tiers.values():
        counts[i] += 1
    risks_l3 = risk_taker_mask(agents, tiers)
    # "crashed into L3": high initial explore, now L3
    crashed_risk = []
    for i, a in enumerate(agents):
        if tiers[i] == 3 and getattr(a, "_risk0", 0) >= float(
            np.median([getattr(x, "_risk0", 0) for x in agents])
        ):
            crashed_risk.append(i)

    arr = np.array(stab_series)
    late_n = max(1, steps // 5)
    return {
        "seed": seed,
        "self_opt_churn": self_opt_churn,
        "risk_reentry": risk_reentry,
        "target": tcoh,
        "mean_stab": float(np.mean(arr)),
        "late_stab": float(np.mean(arr[-late_n:])),
        "min_stab": float(np.min(arr)),
        "max_stab": float(np.max(arr)),
        "locked_frac": float(np.mean(arr >= K.CEILING_SOFT)),
        "final_pair_frac": pair_frac,
        "mean_pair_frac": float(np.mean(pair_series)),
        "tier_L1": counts[1],
        "tier_L2": counts[2],
        "tier_L3": counts[3],
        "risk_takers_in_L3": len(risks_l3),
        "crashed_risk_in_L3": len(crashed_risk),
        "pair_series": pair_series,
        "stab_series": stab_series,
    }


def multi_seed_compare(seeds: list[int], steps: int = 80) -> dict:
    rows = []
    for kind in ("promoted", "reflected"):
        try:
            dna = load_dna(kind)
        except FileNotFoundError as e:
            print(f"  SKIP reflected: {e}")
            continue
        for seed in seeds:
            r = run_episode(dna=dna, seed=seed, steps=steps, self_opt_churn=False, risk_reentry=False)
            r["dna"] = kind
            rows.append(r)
            print(
                f"  dna={kind:10s} seed={seed}  late={r['late_stab']:.4f}  "
                f"lock={r['locked_frac']:.3f}  L3={r['tier_L3']}"
            )
    return {"rows": rows}


def main() -> int:
    print("=" * 64)
    print(" HIVE CHURN SELF-OPT + TIER CENSUS + RISK RE-ENTRY")
    print("=" * 64)

    seeds = [7, 11, 21, 42, 99]
    print("\n[1] Multi-seed DNA: promoted vs reflected")
    cmp_ = multi_seed_compare(seeds, steps=80)

    # Aggregate by dna
    by = {}
    for r in cmp_["rows"]:
        by.setdefault(r["dna"], []).append(r)
    dna_summary = {}
    for k, rs in by.items():
        dna_summary[k] = {
            "late_mean": float(np.mean([x["late_stab"] for x in rs])),
            "lock_mean": float(np.mean([x["locked_frac"] for x in rs])),
            "L3_mean": float(np.mean([x["tier_L3"] for x in rs])),
        }
        print(f"  SUMMARY {k}: late={dna_summary[k]['late_mean']:.4f} lock={dna_summary[k]['lock_mean']:.4f}")

    # Prefer reflected if available and not worse
    use_dna = "reflected" if "reflected" in by else "promoted"
    if "reflected" in dna_summary and "promoted" in dna_summary:
        if dna_summary["reflected"]["late_mean"] + 0.005 < dna_summary["promoted"]["late_mean"]:
            use_dna = "promoted"
            print("  → reflection did not help late stab; using PROMOTED for churn tests")
        else:
            print("  → using REFLECTED DNA for churn tests (helps or ties)")
    dna = load_dna(use_dna)

    print("\n[2] Fixed churn 5% vs self-opt churn (seed=42, 120 steps)")
    fixed = run_episode(dna=dna, seed=42, steps=120, self_opt_churn=False, risk_reentry=False)
    selfopt = run_episode(dna=dna, seed=42, steps=120, self_opt_churn=True, risk_reentry=False)
    print(
        f"  FIXED   late={fixed['late_stab']:.4f} lock={fixed['locked_frac']:.3f} "
        f"L1/L2/L3={fixed['tier_L1']}/{fixed['tier_L2']}/{fixed['tier_L3']} "
        f"risk_L3={fixed['risk_takers_in_L3']}"
    )
    print(
        f"  SELFOPT late={selfopt['late_stab']:.4f} lock={selfopt['locked_frac']:.3f} "
        f"pair_final={selfopt['final_pair_frac']:.3f} mean_pair={selfopt['mean_pair_frac']:.3f} "
        f"L1/L2/L3={selfopt['tier_L1']}/{selfopt['tier_L2']}/{selfopt['tier_L3']} "
        f"risk_L3={selfopt['risk_takers_in_L3']}"
    )

    print("\n[3] Self-opt + risk re-entry vs self-opt only")
    reentry = run_episode(dna=dna, seed=42, steps=120, self_opt_churn=True, risk_reentry=True)
    print(
        f"  REENTRY late={reentry['late_stab']:.4f} lock={reentry['locked_frac']:.3f} "
        f"L1/L2/L3={reentry['tier_L1']}/{reentry['tier_L2']}/{reentry['tier_L3']} "
        f"risk_L3={reentry['risk_takers_in_L3']} crashed_risk_L3={reentry['crashed_risk_in_L3']}"
    )

    # Multi-seed self-opt vs fixed
    print("\n[4] Multi-seed fixed vs self-opt (5 seeds)")
    fix_l, opt_l = [], []
    for s in seeds:
        f = run_episode(dna=dna, seed=s, steps=100, self_opt_churn=False)
        o = run_episode(dna=dna, seed=s, steps=100, self_opt_churn=True)
        fix_l.append(f["late_stab"])
        opt_l.append(o["late_stab"])
        print(f"  seed={s}  fixed_late={f['late_stab']:.4f}  selfopt_late={o['late_stab']:.4f}  "
              f"Δ={o['late_stab']-f['late_stab']:+.4f}  pair→{o['final_pair_frac']:.3f}")

    verdict_opt = float(np.mean(opt_l)) >= float(np.mean(fix_l)) - 0.002
    print(
        f"\n  Multi-seed mean late: fixed={np.mean(fix_l):.4f}  selfopt={np.mean(opt_l):.4f}  "
        f"→ {'SELF-OPT OK' if verdict_opt else 'FIXED SAFER'}"
    )

    # Plots
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True)
    fig.patch.set_facecolor("#0b0f14")
    x = np.arange(len(fixed["stab_series"]))
    ax = axes[0]
    ax.set_facecolor("#0f1620")
    ax.plot(x, fixed["stab_series"], color="#ff6b8a", label="Fixed 5% churn")
    ax.plot(x, selfopt["stab_series"], color="#5dffb0", label="Self-opt churn")
    ax.plot(x, reentry["stab_series"], color="#7ec8ff", label="Self-opt + risk reentry", alpha=0.85)
    ax.axhline(0.92, color="#aaa", ls="--", alpha=0.5)
    ax.axhline(0.925, color="#7ec8ff", ls=":", alpha=0.5)
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_ylabel("Stability", color="white")
    ax.set_title("Hive churn: fixed vs self-opt vs risk re-entry", color="white")
    ax = axes[1]
    ax.set_facecolor("#0f1620")
    ax.plot(np.arange(len(selfopt["pair_series"])), selfopt["pair_series"], color="#ffd060", label="pair_frac self-opt")
    ax.axhline(0.05, color="#ff6b8a", ls="--", alpha=0.6, label="fixed 5%")
    ax.legend(facecolor="#1a2332", labelcolor="white", fontsize=8)
    ax.tick_params(colors="white")
    ax.set_xlabel("Step", color="white")
    ax.set_ylabel("PAIR_FRAC", color="white")
    for a in axes:
        for s in a.spines.values():
            s.set_color("#445")
    fig.tight_layout()
    fig.savefig(OUT / "hive_churn_selfopt.png", dpi=140, facecolor=fig.get_facecolor())
    plt.close(fig)

    report = {
        "dna_used": use_dna,
        "dna_summary": dna_summary,
        "fixed": {k: v for k, v in fixed.items() if k not in ("pair_series", "stab_series")},
        "selfopt": {k: v for k, v in selfopt.items() if k not in ("pair_series", "stab_series")},
        "reentry": {k: v for k, v in reentry.items() if k not in ("pair_series", "stab_series")},
        "multiseed_fixed_late_mean": float(np.mean(fix_l)),
        "multiseed_selfopt_late_mean": float(np.mean(opt_l)),
        "selfopt_verdict": "OK" if verdict_opt else "PREFER_FIXED",
        "tier_definitions": {
            "L1": "top ~20% performance (elites)",
            "L2": "middle ~60%",
            "L3": "bottom ~20% (struggling / crashed band)",
            "risk_taker_L3": "L3 with explore_bias >= median",
            "crashed_risk_L3": "L3 who started as above-median explorers",
        },
    }
    (OUT / "hive_churn_selfopt_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Honest recommendations
    print("\n" + "=" * 64)
    print(" TIER CENSUS (seed=42, end of 120-step run)")
    print("=" * 64)
    print(f"  Fixed   L1/L2/L3 = {fixed['tier_L1']}/{fixed['tier_L2']}/{fixed['tier_L3']}  "
          f"(risk-takers in L3: {fixed['risk_takers_in_L3']})")
    print(f"  Selfopt L1/L2/L3 = {selfopt['tier_L1']}/{selfopt['tier_L2']}/{selfopt['tier_L3']}  "
          f"(risk-takers in L3: {selfopt['risk_takers_in_L3']})")
    print(f"  Reentry L1/L2/L3 = {reentry['tier_L1']}/{reentry['tier_L2']}/{reentry['tier_L3']}  "
          f"(risk-takers in L3: {reentry['risk_takers_in_L3']}, crashed_risk: {reentry['crashed_risk_in_L3']})")
    print(f"\n  Plot → {OUT / 'hive_churn_selfopt.png'}")
    print(f"  JSON → {OUT / 'hive_churn_selfopt_results.json'}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
