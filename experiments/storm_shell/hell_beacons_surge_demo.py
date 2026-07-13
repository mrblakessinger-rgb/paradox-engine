"""
Beacons + Surge Shield — Hell Incarnate stress harness
======================================================
Defense stack on top of PROMOTED DNA (frozen — no promote):

  SURGE SHIELD  — attenuate felt interference + clip surge violence under storm
  BEACONS       — high-coherence core attractors pull edge agents toward core
  EXPAND-L2     — optional mid-band flex + soft absorb (from expand_l2_demo)

Paradox still: install_drivers + hive_pair_churn each step (one-way).
Swarm never stores Paradox. Anti-lock ceiling held.

Goal: wrangle under extreme noise, map BREAK points, decide:
  A) fold defense into primary kernel later, or
  B) keep as a second "storm engine" for different regimes

  python real_world/hell_beacons_surge_demo.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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

# Break thresholds (honest "we lost the fleet" lines)
HARD_BREAK_LATE = 0.70
HARD_BREAK_MIN = 0.35
SOFT_BREAK_EDGE = 0.55
SOFT_BREAK_LATE = 0.85


# ---------------------------------------------------------------------------
# Defense modules
# ---------------------------------------------------------------------------
@dataclass
class DefenseConfig:
    surge_shield: bool = False
    beacons: bool = False
    expand_l2: bool = False
    # surge
    shield_I_floor: float = 1.8
    shield_max_cut: float = 0.42  # felt_I = I * (1 - cut), cut up to this
    surge_clip: float = 0.55  # multiply post-step flux violence under shield
    # beacons
    beacon_I_on: float = 2.0
    n_beacons: int = 5
    beacon_pull: float = 0.14
    beacon_flux_damp: float = 0.90
    edge_frac: float = 0.22
    # L2
    l2_absorb: bool = True


def assign_tiers(agents, bottom_frac=0.20, top_frac=0.20) -> dict[int, int]:
    n = len(agents)
    order = np.argsort([a.performance for a in agents])
    n3 = max(1, int(round(n * bottom_frac)))
    n1 = max(1, int(round(n * top_frac)))
    l3 = set(int(i) for i in order[:n3])
    l1 = set(int(i) for i in order[-n1:])
    out = {}
    for i in range(n):
        if i in l1:
            out[i] = 1
        elif i in l3:
            out[i] = 3
        else:
            out[i] = 2
    return out


def surge_shield_scale(I: float, stab: float, cfg: DefenseConfig) -> float:
    """
    Felt load multiplier in (1-max_cut) .. 1.0
    Stronger when I high AND kernel still has some coherence to protect.
    Weak/none when already dead (don't fake stability with infinite shield).
    """
    if not cfg.surge_shield or I < cfg.shield_I_floor:
        return 1.0
    # how deep into storm
    depth = float(np.clip((I - cfg.shield_I_floor) / 2.5, 0, 1))
    # need some stability to "hold the shield up"
    hold = float(np.clip((stab - 0.40) / 0.50, 0, 1))
    cut = cfg.shield_max_cut * depth * (0.35 + 0.65 * hold)
    return float(np.clip(1.0 - cut, 1.0 - cfg.shield_max_cut, 1.0))


def apply_surge_aftermath(agents, I: float, cfg: DefenseConfig, shield_scale: float) -> None:
    """Extra damp on flux/velocity when shield is active (surge violence)."""
    if not cfg.surge_shield or shield_scale >= 0.98:
        return
    strength = (1.0 - shield_scale) / max(cfg.shield_max_cut, 1e-6)
    damp = 1.0 - (1.0 - cfg.surge_clip) * strength * min(1.0, I / 3.0)
    damp = float(np.clip(damp, 0.45, 1.0))
    for a in agents:
        a.flux *= damp
        a.velocity *= 0.5 + 0.5 * damp


def apply_beacons(agents, I: float, cfg: DefenseConfig, target: float = TARGET) -> int:
    """
    Core attractors: top-n by coherence emit pull on edge (bottom edge_frac).
    Returns number of edge agents pulled.
    """
    if not cfg.beacons or I < cfg.beacon_I_on:
        return 0
    n = len(agents)
    order = np.argsort([a.coherence for a in agents])  # low → high
    n_edge = max(1, int(round(n * cfg.edge_frac)))
    edge_idx = [int(i) for i in order[:n_edge]]
    beacon_idx = [int(i) for i in order[-cfg.n_beacons :]]
    if not beacon_idx:
        return 0
    core = float(np.mean([agents[i].coherence for i in beacon_idx]))
    # intensity scales with I and how far core is above edge
    intensity = float(np.clip((I - cfg.beacon_I_on) / 2.0, 0, 1.25))
    pull = cfg.beacon_pull * (0.55 + 0.45 * intensity)
    pulled = 0
    for i in edge_idx:
        a = agents[i]
        # toward core mean, not toward 1.0
        a.coherence = float(
            np.clip(
                (1.0 - pull) * a.coherence + pull * core + 0.02 * (target - a.coherence),
                0.0,
                CEILING,
            )
        )
        a.flux = float(np.clip(a.flux * cfg.beacon_flux_damp, -2.5, 2.5))
        a.velocity *= 0.92
        pulled += 1
    # mild core tax — beacons spend a little energy (no free lunch)
    tax = 0.008 * intensity
    for i in beacon_idx:
        agents[i].coherence = float(np.clip(agents[i].coherence - tax, 0.0, CEILING))
    return pulled


def adaptive_band_fracs(I: float) -> tuple[float, float]:
    if I >= 2.6:
        return 0.12, 0.12
    if I >= 2.0:
        return 0.15, 0.15
    return 0.20, 0.20


def flex_l2_and_absorb(agents, tiers, I, cfg: DefenseConfig, rng) -> int:
    if not cfg.expand_l2:
        return 0
    # instinct flex L2
    high_i = I >= 2.0
    for i, a in enumerate(agents):
        if tiers.get(i) != 2:
            continue
        inst = a.instinct
        if high_i:
            inst["damper_bias"] = float(np.clip(inst.get("damper_bias", 1.0) * 1.035, 0.3, 2.4))
            inst["repair_bias"] = float(np.clip(inst.get("repair_bias", 1.0) * 1.03, 0.3, 2.4))
            inst["viscosity_bias"] = float(np.clip(inst.get("viscosity_bias", 1.0) * 1.02, 0.3, 2.4))
        else:
            inst["explore_bias"] = float(
                np.clip(inst.get("explore_bias", 0.3) * 1.01 + 0.004, 0.05, 0.55)
            )
    if not cfg.l2_absorb or I < 1.8:
        return 0
    l2 = sorted(
        [i for i, t in tiers.items() if t == 2],
        key=lambda i: agents[i].performance,
        reverse=True,
    )
    l3 = sorted(
        [i for i, t in tiers.items() if t == 3],
        key=lambda i: agents[i].performance,
    )
    n = min(2 + (1 if I >= 2.5 else 0), len(l2), len(l3))
    for k in range(n):
        a, b = agents[l2[k]], agents[l3[k]]
        pull = 0.11 + 0.04 * min(1.0, (I - 1.8) / 1.5)
        b.coherence = float(np.clip(0.72 * b.coherence + pull * a.coherence + 0.025, 0, CEILING))
        b.flux *= 0.88
    return n


# ---------------------------------------------------------------------------
# Environment scenarios (Paradox "plays" across these)
# ---------------------------------------------------------------------------
ScenarioFn = Callable[[int, int, np.random.Generator, float], float]


def scen_mild(t, steps, rng, I):
    if rng.random() < 0.08:
        return float(rng.choice([0.7, 1.2, 1.6, 2.0]))
    return float(np.clip(I + rng.normal(0, 0.06), 0.5, 2.2))


def scen_cruel(t, steps, rng, I):
    if t < 12:
        return float(np.clip(1.3 + rng.normal(0, 0.05), 0.8, 1.7))
    if t < 50:
        return float(np.clip(2.85 + rng.normal(0, 0.05), 2.5, 3.0))
    if t < 70:
        return float(rng.choice([2.3, 2.6, 2.9]))
    return float(np.clip(I + rng.normal(0, 0.1), 1.0, 2.8))


def scen_hell_incarnate(t, steps, rng, I):
    """Designed to find the cliff — I past training band + spikes."""
    if t < 8:
        return float(1.5 + rng.uniform(0, 0.3))
    if t < 40:
        # sustained beyond normal kernel band (was ~3.0 max in demos)
        return float(np.clip(3.6 + rng.normal(0, 0.15), 3.2, 4.2))
    if t < 55:
        return float(rng.choice([4.0, 4.5, 5.0, 3.5]))
    if t < 75:
        # thrash jumps
        return float(rng.choice([1.0, 2.5, 4.5, 5.5, 3.0]))
    return float(np.clip(3.0 + rng.normal(0, 0.4), 1.5, 5.0))


def scen_flicker(t, steps, rng, I):
    """Violent I jumps every few steps — anti-prediction."""
    if t % 3 == 0:
        return float(rng.choice([0.5, 1.0, 2.0, 3.0, 4.0, 4.8]))
    return float(np.clip(I + rng.normal(0, 0.35), 0.4, 5.0))


def scen_noise_flood(t, steps, rng, I):
    """Moderate I but external will inject huge flux noise (flag on env)."""
    base = 2.2 + 0.3 * np.sin(t / 5.0)
    return float(np.clip(base + rng.normal(0, 0.12), 1.5, 3.2))


def scen_beyond_map(t, steps, rng, I):
    """I stays in 4.5–6.0 — pure overpressure."""
    return float(np.clip(5.0 + rng.normal(0, 0.35), 4.2, 6.0))


SCENARIOS: dict[str, dict] = {
    "mild": {"fn": scen_mild, "noise_amp": 1.0, "shock": 0.0, "hive": True, "start_hurt": 0.0},
    "cruel": {"fn": scen_cruel, "noise_amp": 1.15, "shock": 0.02, "hive": True, "start_hurt": 0.08},
    "hell_incarnate": {
        "fn": scen_hell_incarnate,
        "noise_amp": 1.6,
        "shock": 0.06,
        "hive": True,
        "start_hurt": 0.15,
    },
    "flicker": {"fn": scen_flicker, "noise_amp": 1.4, "shock": 0.04, "hive": True, "start_hurt": 0.10},
    "noise_flood": {
        "fn": scen_noise_flood,
        "noise_amp": 2.4,
        "shock": 0.08,
        "hive": True,
        "start_hurt": 0.12,
    },
    "beyond_map": {
        "fn": scen_beyond_map,
        "noise_amp": 1.8,
        "shock": 0.10,
        "hive": True,
        "start_hurt": 0.18,
    },
    "hell_no_hive": {
        "fn": scen_hell_incarnate,
        "noise_amp": 1.6,
        "shock": 0.06,
        "hive": False,
        "start_hurt": 0.15,
    },
    "hell_solo_paradox": {
        # hive on, but we reinstall drivers harder (Paradox more active)
        "fn": scen_hell_incarnate,
        "noise_amp": 1.7,
        "shock": 0.07,
        "hive": True,
        "start_hurt": 0.15,
        "paradox_tight": True,
    },
}


STACKS: dict[str, DefenseConfig] = {
    "baseline": DefenseConfig(),
    "surge_only": DefenseConfig(surge_shield=True),
    "beacons_only": DefenseConfig(beacons=True),
    "l2_only": DefenseConfig(expand_l2=True),
    "surge_beacons": DefenseConfig(surge_shield=True, beacons=True),
    "full_defense": DefenseConfig(surge_shield=True, beacons=True, expand_l2=True),
}


@dataclass
class EpisodeResult:
    scenario: str
    stack: str
    seed: int
    late_stab: float
    mean_stab: float
    min_stab: float
    hell_min: float
    edge_coh_final: float
    locked_frac: float
    mean_I: float
    max_I: float
    beacon_pulls: int
    absorb_n: int
    mean_shield: float
    hard_break: bool
    soft_break: bool
    stab_series: list = field(default_factory=list)
    I_series: list = field(default_factory=list)


def classify_break(r: EpisodeResult) -> str:
    if r.hard_break:
        return "HARD"
    if r.soft_break:
        return "SOFT"
    if r.late_stab >= TARGET - 0.04:
        return "HOLD"
    if r.late_stab >= SOFT_BREAK_LATE:
        return "OK"
    return "WEAK"


def run_episode(
    *,
    scenario: str,
    stack: str,
    seed: int,
    steps: int = 100,
    target: float = TARGET,
) -> EpisodeResult:
    meta = SCENARIOS[scenario]
    cfg = STACKS[stack]
    fn: ScenarioFn = meta["fn"]
    noise_amp = float(meta["noise_amp"])
    shock = float(meta["shock"])
    use_hive = bool(meta["hive"])
    start_hurt = float(meta["start_hurt"])
    paradox_tight = bool(meta.get("paradox_tight", False))

    rng = np.random.default_rng(seed)
    agents = K.make_swarm(rng)
    if start_hurt > 0:
        for a in agents:
            a.coherence = float(
                np.clip(a.coherence * (1.0 - start_hurt) + rng.uniform(-0.06, 0.02), 0.15, 0.70)
            )
            a.flux = float(a.flux + rng.normal(0, 0.2 + start_hurt))

    dna = {
        **K.PROMOTED_DNA,
        "intuition": {**K.PROMOTED_DNA["intuition"], "target_coherence": float(target)},
    }
    paradox = K.Paradox(dna)
    paradox.install_drivers(agents)

    stab_series = []
    I_series = []
    edge_series = []
    shield_series = []
    beacon_pulls = 0
    absorb_n = 0
    ambient = 0.0
    I = 1.5
    prev_stab = 0.55

    for t in range(steps):
        I = float(fn(t, steps, rng, I))
        I_series.append(I)

        # provisional stab for shield (use previous)
        shield = surge_shield_scale(I, prev_stab, cfg)
        shield_series.append(shield)
        felt_I = I * shield

        for a in agents:
            a.step(felt_I, ambient, rng)

        # external noise flood / shock (environment, not DNA)
        if noise_amp > 1.0 or shock > 0:
            for a in agents:
                a.flux = float(
                    np.clip(
                        a.flux + rng.normal(0, 0.05 * (noise_amp - 1.0) * max(I, 1.0)),
                        -2.5,
                        2.5,
                    )
                )
                if shock > 0 and rng.random() < 0.12:
                    a.coherence = float(
                        np.clip(a.coherence - shock * rng.random() * (I / 3.0), 0, CEILING)
                    )

        apply_surge_aftermath(agents, I, cfg, shield)

        for a in agents:
            tc = a.instinct.get("target_coherence", target)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )

        bot_f, top_f = adaptive_band_fracs(I) if cfg.expand_l2 else (0.20, 0.20)
        tiers = assign_tiers(agents, bottom_frac=bot_f, top_frac=top_f)
        absorb_n += flex_l2_and_absorb(agents, tiers, I, cfg, rng)
        beacon_pulls += apply_beacons(agents, I, cfg, target=target)

        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        if use_hive:
            paradox.hive_pair_churn(agents, rng)
        if paradox_tight:
            # Paradox re-stamps drivers more aggressively each step
            paradox.install_drivers(agents)
            paradox.install_drivers(agents)
        else:
            paradox.install_drivers(agents)

        stab = K.stability(agents)
        stab_series.append(stab)
        prev_stab = stab
        order = np.argsort([a.coherence for a in agents])
        n_edge = max(1, int(0.2 * len(agents)))
        edge_series.append(float(np.mean([agents[int(i)].coherence for i in order[:n_edge]])))

    arr = np.array(stab_series)
    late_n = max(1, steps // 5)
    late = float(np.mean(arr[-late_n:]))
    # "hell window" ~ mid-early peak violence
    hell_slice = arr[8:55] if len(arr) > 55 else arr
    edge_final = float(edge_series[-1]) if edge_series else 0.0
    min_stab = float(np.min(arr))
    hard = late < HARD_BREAK_LATE or min_stab < HARD_BREAK_MIN
    soft = (not hard) and (late < SOFT_BREAK_LATE or edge_final < SOFT_BREAK_EDGE)

    return EpisodeResult(
        scenario=scenario,
        stack=stack,
        seed=seed,
        late_stab=late,
        mean_stab=float(np.mean(arr)),
        min_stab=min_stab,
        hell_min=float(np.min(hell_slice)),
        edge_coh_final=edge_final,
        locked_frac=float(np.mean(arr >= CEILING)),
        mean_I=float(np.mean(I_series)),
        max_I=float(np.max(I_series)),
        beacon_pulls=int(beacon_pulls),
        absorb_n=int(absorb_n),
        mean_shield=float(np.mean(shield_series)),
        hard_break=hard,
        soft_break=soft,
        stab_series=stab_series,
        I_series=I_series,
    )


def aggregate(results: list[EpisodeResult]) -> dict:
    return {
        "n": len(results),
        "late_mean": float(np.mean([r.late_stab for r in results])),
        "late_std": float(np.std([r.late_stab for r in results])),
        "min_mean": float(np.mean([r.min_stab for r in results])),
        "hell_min_mean": float(np.mean([r.hell_min for r in results])),
        "edge_mean": float(np.mean([r.edge_coh_final for r in results])),
        "hard_rate": float(np.mean([r.hard_break for r in results])),
        "soft_rate": float(np.mean([r.soft_break for r in results])),
        "hold_rate": float(np.mean([classify_break(r) == "HOLD" for r in results])),
        "lock_mean": float(np.mean([r.locked_frac for r in results])),
        "mean_I": float(np.mean([r.mean_I for r in results])),
        "max_I_seen": float(np.max([r.max_I for r in results])),
    }


def main() -> int:
    print("=" * 72)
    print(" BEACONS + SURGE SHIELD — HELL INCARNATE HARNESS")
    print(" DNA: PROMOTED frozen · Paradox installs drivers · defense is modular")
    print("=" * 72)

    seeds = [7, 21, 42, 99]
    steps = 100
    # Full matrix would be huge; focus stacks × scenarios
    focus_stacks = [
        "baseline",
        "surge_only",
        "beacons_only",
        "surge_beacons",
        "full_defense",
    ]
    focus_scenarios = [
        "mild",
        "cruel",
        "hell_incarnate",
        "flicker",
        "noise_flood",
        "beyond_map",
        "hell_no_hive",
        "hell_solo_paradox",
    ]

    all_rows: list[EpisodeResult] = []
    matrix: dict[str, dict[str, dict]] = {}

    for scen in focus_scenarios:
        matrix[scen] = {}
        print(f"\n### SCENARIO: {scen}")
        for stack in focus_stacks:
            rs = [
                run_episode(scenario=scen, stack=stack, seed=s, steps=steps) for s in seeds
            ]
            all_rows.extend(rs)
            agg = aggregate(rs)
            matrix[scen][stack] = agg
            tag = (
                "HARD"
                if agg["hard_rate"] >= 0.5
                else ("SOFT" if agg["soft_rate"] >= 0.5 else ("HOLD" if agg["hold_rate"] >= 0.5 else "MIX"))
            )
            print(
                f"  {stack:14s}  late={agg['late_mean']:.3f}  min={agg['min_mean']:.3f}  "
                f"edge={agg['edge_mean']:.3f}  hard%={100*agg['hard_rate']:.0f}  "
                f"hold%={100*agg['hold_rate']:.0f}  [{tag}]  Iμ={agg['mean_I']:.2f}"
            )

    # --- Verdict tables ---
    print("\n" + "=" * 72)
    print(" BREAK MAP (hard% across seeds) — where each stack dies")
    print("=" * 72)
    header = f"{'scenario':18s}" + "".join(f"{s[:10]:>11s}" for s in focus_stacks)
    print(header)
    for scen in focus_scenarios:
        line = f"{scen:18s}"
        for stack in focus_stacks:
            line += f"{100*matrix[scen][stack]['hard_rate']:10.0f}%"
        print(line)

    print("\n LATE STAB mean")
    print(header)
    for scen in focus_scenarios:
        line = f"{scen:18s}"
        for stack in focus_stacks:
            line += f"{matrix[scen][stack]['late_mean']:11.3f}"
        print(line)

    # --- Find cliffs: first scenario where baseline hard_rate > 0.5 ---
    print("\n" + "=" * 72)
    print(" LIMITS & FIT")
    print("=" * 72)

    def best_stack_for(scen: str) -> str:
        return max(
            focus_stacks,
            key=lambda s: (
                matrix[scen][s]["late_mean"] - 0.15 * matrix[scen][s]["hard_rate"],
                -matrix[scen][s]["hard_rate"],
            ),
        )

    recommendations = []
    for scen in focus_scenarios:
        b = best_stack_for(scen)
        base = matrix[scen]["baseline"]
        full = matrix[scen]["full_defense"]
        sb = matrix[scen]["surge_beacons"]
        recommendations.append(
            {
                "scenario": scen,
                "best_stack": b,
                "baseline_late": base["late_mean"],
                "baseline_hard": base["hard_rate"],
                "full_late": full["late_mean"],
                "full_hard": full["hard_rate"],
                "surge_beacons_late": sb["late_mean"],
                "surge_beacons_hard": sb["hard_rate"],
                "delta_late_full": full["late_mean"] - base["late_mean"],
                "delta_hard_full": full["hard_rate"] - base["hard_rate"],
            }
        )
        print(
            f"  {scen:18s} best={b:14s}  "
            f"base late={base['late_mean']:.3f} hard%={100*base['hard_rate']:.0f}  "
            f"full Δlate={full['late_mean']-base['late_mean']:+.3f} "
            f"Δhard%={100*(full['hard_rate']-base['hard_rate']):+.0f}"
        )

    # Dual-engine decision heuristic
    mild_ok = matrix["mild"]["baseline"]["hold_rate"] >= 0.75
    hell_base_dead = matrix["hell_incarnate"]["baseline"]["hard_rate"] >= 0.5
    hell_full_helps = (
        matrix["hell_incarnate"]["full_defense"]["late_mean"]
        > matrix["hell_incarnate"]["baseline"]["late_mean"] + 0.02
        or matrix["hell_incarnate"]["full_defense"]["hard_rate"]
        < matrix["hell_incarnate"]["baseline"]["hard_rate"] - 0.24
    )
    beyond_still_dead = matrix["beyond_map"]["full_defense"]["hard_rate"] >= 0.75
    mild_full_not_worse = (
        matrix["mild"]["full_defense"]["late_mean"]
        >= matrix["mild"]["baseline"]["late_mean"] - 0.02
    )

    print("\n[ENGINE DECISION SIGNALS]")
    print(f"  primary holds mild:     {mild_ok}")
    print(f"  hell kills baseline:    {hell_base_dead}")
    print(f"  full_defense helps hell:{hell_full_helps}")
    print(f"  beyond_map still breaks:{beyond_still_dead}")
    print(f"  full not hurting mild:  {mild_full_not_worse}")

    if mild_ok and hell_full_helps and mild_full_not_worse and not beyond_still_dead:
        verdict = (
            "MERGE_CANDIDATE: defense helps hell without spoiling mild — "
            "consider folding surge+beacons as optional KERNEL storm mode later."
        )
    elif mild_ok and hell_full_helps and beyond_still_dead:
        verdict = (
            "DUAL_REGIME: primary owns normal/cruel; storm pack (surge+beacons[+L2]) "
            "extends hell but still has a cliff (beyond_map). Keep as modular defense "
            "engine / actuate skin — not a second product DNA. Wire when env_load extreme."
        )
    elif mild_ok and not hell_full_helps:
        verdict = (
            "PRIMARY_WINS: defense stack does not earn its complexity under hell. "
            "Keep experiments; do not promote. Primary Paradox kernel remains the engine."
        )
    else:
        verdict = (
            "RETHINK: mixed signals — inspect matrix before any promote or product claim."
        )
    print(f"\n  VERDICT → {verdict}")

    # --- Plots: hell_incarnate seed=42 all stacks ---
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)
    ax = axes[0]
    colors = {
        "baseline": "#888888",
        "surge_only": "#3498db",
        "beacons_only": "#e67e22",
        "surge_beacons": "#9b59b6",
        "full_defense": "#2ecc71",
    }
    for stack in focus_stacks:
        r = run_episode(scenario="hell_incarnate", stack=stack, seed=42, steps=120)
        ax.plot(r.stab_series, label=stack, color=colors.get(stack, None), lw=1.6)
    ax.axhline(TARGET, color="#2980b9", ls="--", lw=1)
    ax.axhline(HARD_BREAK_LATE, color="#c0392b", ls=":", lw=1, label="hard late line")
    ax.set_ylabel("stability")
    ax.set_title("Hell incarnate — stacks (seed=42)")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_ylim(0.0, 1.02)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    # bar: late_mean by scenario for baseline vs full
    x = np.arange(len(focus_scenarios))
    w = 0.35
    base_l = [matrix[s]["baseline"]["late_mean"] for s in focus_scenarios]
    full_l = [matrix[s]["full_defense"]["late_mean"] for s in focus_scenarios]
    ax2.bar(x - w / 2, base_l, w, label="baseline", color="#888")
    ax2.bar(x + w / 2, full_l, w, label="full_defense", color="#2ecc71")
    ax2.axhline(TARGET, color="#2980b9", ls="--", lw=1)
    ax2.axhline(HARD_BREAK_LATE, color="#c0392b", ls=":", lw=1)
    ax2.set_xticks(x)
    ax2.set_xticklabels(focus_scenarios, rotation=25, ha="right", fontsize=8)
    ax2.set_ylabel("late stability")
    ax2.set_title("Late stab: baseline vs full defense across scenarios")
    ax2.legend(fontsize=8)
    ax2.set_ylim(0, 1.05)
    ax2.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    png = OUT / "hell_beacons_surge.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # cliff ladder: baseline vs full on increasing cruelty
    ladder = ["mild", "cruel", "hell_incarnate", "beyond_map"]
    fig2, ax3 = plt.subplots(figsize=(9, 5))
    for stack, col in [("baseline", "#888"), ("surge_beacons", "#9b59b6"), ("full_defense", "#2ecc71")]:
        ys = [matrix[s][stack]["late_mean"] for s in ladder]
        hs = [matrix[s][stack]["hard_rate"] for s in ladder]
        ax3.plot(ladder, ys, "o-", color=col, lw=2, label=f"{stack} late")
        ax3.plot(ladder, hs, "s--", color=col, lw=1, alpha=0.7, label=f"{stack} hard%")
    ax3.set_ylabel("late stab / hard rate")
    ax3.set_title("Cliff ladder: mild → beyond_map")
    ax3.legend(fontsize=7, ncol=2)
    ax3.grid(True, alpha=0.25)
    fig2.tight_layout()
    png2 = OUT / "hell_cliff_ladder.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "beacons_surge_hell_v1",
        "dna": "PROMOTED_FROZEN",
        "target": TARGET,
        "break_lines": {
            "hard_late": HARD_BREAK_LATE,
            "hard_min": HARD_BREAK_MIN,
            "soft_edge": SOFT_BREAK_EDGE,
            "soft_late": SOFT_BREAK_LATE,
        },
        "seeds": seeds,
        "steps": steps,
        "stacks": list(focus_stacks),
        "scenarios": list(focus_scenarios),
        "matrix": matrix,
        "per_scenario_best": recommendations,
        "verdict": verdict,
        "fit_notes": {
            "primary_kernel": "Owns mild/cruel when promoted DNA already holds; buyer Soft Pack path.",
            "surge_shield": "Cuts felt I under storm; needs residual stab to hold shield.",
            "beacons": "Edge→core pull under high I; small core tax; anti-lock capped.",
            "expand_l2": "Mid-band flex; stacks on full_defense.",
            "hell_incarnate": "I past ~3.5–5 + noise/shock — finds cliffs.",
            "beyond_map": "I~5 sustained — expected break zone for honesty.",
        },
    }
    # numpy types already floats
    js = OUT / "hell_beacons_surge_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
