"""
Toughen (3.0 ↔ 6.4 irregular ramps) × 3 cycles → Hell-incarnate eval
====================================================================
TRAIN schedule (several ramps per cycle):
  - Baseline floor I≈3.0
  - Climb to 6.4, descend to ~3.0
  - Irregular spikes back to 6.4 (random dwell / partial climbs)
  - Repeat multiple ramp blocks per cycle
  - 3 full train cycles with Paradox scar→wisdom learning + storm shell

EVAL (post-train, frozen learned intuition vs control):
  Re-run hell-style scenarios from hell_beacons_surge harness:
    mild, cruel, hell_incarnate, flicker, noise_flood, beyond_map,
    hell_no_hive, annihilation-ish

Compare:
  A) baseline PROMOTED + no shell (reference)
  B) PROMOTED + shell, no toughen
  C) toughened Paradox (3 cycles) + shell
  D) toughened, then shell OFF at eval (did instincts alone improve?)

  python real_world/toughen_then_hell_eval.py
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

def _find_root() -> Path:
    p = Path(__file__).resolve().parent
    for _ in range(6):
        if (p / 'KERNEL_v1.py').exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[2]

ROOT = _find_root()
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import KERNEL_v1 as K
from storm_surge_learn_cycles import (  # noqa: E402
    StormShell,
    edge_coh,
    TARGET,
    CEILING,
    HARD_LATE,
    HARD_MIN,
    SOFT_LATE,
)
import hell_beacons_surge_demo as H  # noqa: E402

OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

N_TOUGHEN_CYCLES = 3
TRAIN_SEEDS = [7, 21, 42, 99]
EVAL_SEEDS = [7, 21, 42, 99]


# ---------------------------------------------------------------------------
# I schedule: 3.0 standard, ramp to 6.4, down, irregular re-attacks
# ---------------------------------------------------------------------------
def build_toughen_I_schedule(steps: int, rng: np.random.Generator) -> list[float]:
    """
    Several ramp blocks per cycle.
    Each block roughly: hold~3.0 → climb to 6.4 → hold peak briefly →
    descend to ~3.0 → irregular spikes toward 6.4 → settle.
    """
    I_list: list[float] = []
    t = 0
    # number of major ramp blocks
    n_blocks = 5
    block_len = steps // n_blocks

    for b in range(n_blocks):
        # remaining steps for last block
        if b == n_blocks - 1:
            blen = steps - t
        else:
            blen = block_len
        # sub-phases fractions
        # 0-15% hold 3.0, 15-40% climb, 40-50% peak, 50-70% descend,
        # 70-100% irregular attacks
        for k in range(blen):
            u = k / max(blen - 1, 1)
            if u < 0.12:
                I = 3.0 + rng.normal(0, 0.06)
            elif u < 0.38:
                # climb 3.0 → 6.4
                p = (u - 0.12) / 0.26
                # ease-in-out
                p = p * p * (3 - 2 * p)
                I = 3.0 + p * (6.4 - 3.0) + rng.normal(0, 0.08)
            elif u < 0.48:
                I = 6.4 + rng.normal(0, 0.12)
            elif u < 0.68:
                p = (u - 0.48) / 0.20
                p = p * p * (3 - 2 * p)
                I = 6.4 - p * (6.4 - 3.05) + rng.normal(0, 0.10)
            else:
                # irregular: random partial or full re-spikes to 6.4
                r = rng.random()
                if r < 0.22:
                    # full spike
                    I = 6.4 + rng.normal(0, 0.15)
                elif r < 0.45:
                    # partial spike 4.5–5.8
                    I = float(rng.uniform(4.5, 5.8))
                elif r < 0.65:
                    # mid thrash
                    I = float(rng.uniform(3.5, 4.8))
                else:
                    I = 3.0 + rng.normal(0, 0.15)
            I_list.append(float(np.clip(I, 2.5, 6.6)))
            t += 1
    # pad/truncate
    while len(I_list) < steps:
        I_list.append(3.0)
    return I_list[:steps]


def run_toughen_cycle(
    *,
    cycle: int,
    seed: int,
    paradox: K.Paradox,
    shell: StormShell,
    steps: int = 160,
) -> dict:
    rng = np.random.default_rng(seed + 5000 * cycle)
    agents = K.make_swarm(rng)
    hurt = 0.08 + 0.025 * (cycle - 1)
    for a in agents:
        a.coherence = float(
            np.clip(a.coherence * (1.0 - hurt) + rng.uniform(-0.04, 0.02), 0.15, 0.70)
        )
        a.flux += float(rng.normal(0, 0.12))

    paradox.install_drivers(agents)
    cm = float(paradox.intuition.get("countermeasure_invest", 0.5))
    I_sched = build_toughen_I_schedule(steps, rng)

    stab_series = []
    shield_series = []
    scars = []
    ambient = 0.0
    prev_stab = 0.55
    prev_prev = 0.55
    prev_I = 3.0
    first_soft = None
    first_hard = None
    peak_I = 0.0
    time_above_5 = 0
    time_at_peak = 0  # near 6.4

    for t in range(steps):
        I = I_sched[t]
        peak_I = max(peak_I, I)
        if I >= 5.0:
            time_above_5 += 1
        if I >= 6.2:
            time_at_peak += 1

        dI = I - prev_I
        dS = prev_stab - prev_prev
        scale = shell.scale(I, prev_stab, dI, dS, countermeasure=cm)
        felt = I * scale
        shield_series.append(scale)

        # tougher noise when I high
        noise_amp = 1.0 + 0.35 * min(1.0, (I - 3.0) / 3.4)
        shock = 0.02 + 0.12 * min(1.0, max(0.0, I - 4.0) / 2.4)

        for a in agents:
            a.step(felt, ambient, rng)
        for a in agents:
            a.flux = float(
                np.clip(
                    a.flux + rng.normal(0, 0.04 * noise_amp * (I / 4.0)),
                    -2.5,
                    2.5,
                )
            )
            if shock > 0 and rng.random() < 0.12:
                a.coherence = float(
                    np.clip(a.coherence - shock * rng.random() * (I / 5.0), 0, CEILING)
                )

        shell.aftermath(agents, I, scale)
        shell.beacons_pull(agents, I)

        for a in agents:
            tc = a.instinct.get("target_coherence", TARGET)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )

        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, rng)
        paradox.install_drivers(agents)

        stab = K.stability(agents)
        stab_series.append(stab)

        if t > 0 and stab < prev_stab - 0.02:
            scars.append({"reason": "tighten_storm", "I": I, "stab": stab})
        if t > 0 and stab > prev_stab + 0.015 and I < 4.0:
            scars.append({"reason": "climb_recover", "I": I, "stab": stab})
        if I >= 6.0 and stab >= 0.75:
            scars.append({"reason": "climb_hold_peak", "I": I, "stab": stab})
        if I >= 5.5 and stab < SOFT_LATE:
            scars.append({"reason": "tighten_high_I_floor", "I": I, "stab": stab})
        if stab < SOFT_LATE and first_soft is None:
            first_soft = t
            scars.append({"reason": "soft_floor", "I": I, "stab": stab})
        if (stab < HARD_LATE or stab < HARD_MIN) and first_hard is None:
            first_hard = t
            scars.append({"reason": "hard_break_threat", "I": I, "stab": stab})

        prev_I = I
        prev_prev = prev_stab
        prev_stab = stab

    arr = np.array(stab_series)
    late_n = max(1, steps // 6)
    late = float(np.mean(arr[-late_n:]))
    # metrics on high-I windows
    high_idx = [i for i, I in enumerate(I_sched) if I >= 5.5]
    high_stab = float(np.mean([arr[i] for i in high_idx])) if high_idx else late

    if len(scars) > 100:
        scars = scars[-100:]

    meta = {
        "final_alive": late >= HARD_LATE,
        "first_soft_break": first_soft,
        "first_hard_break": first_hard if late < HARD_LATE or float(np.min(arr)) < HARD_MIN else None,
        "recovery_peak": float(np.max(arr[-max(1, steps // 5) :])),
        "recovery_late": late,
        "survived_long_hell": first_hard is None and high_stab > 0.72,
        "peak_I": peak_I,
        "time_above_5": time_above_5,
        "time_at_peak": time_at_peak,
        "high_I_stab": high_stab,
        "cycle": cycle,
    }

    paradox.absorb_episode(scars, episode_meta=meta)
    report = paradox.compress_scars_to_wisdom(max_intuition_delta=0.08)
    # toughen-specific: exposure to 6.4 → invest countermeasure + damper
    if high_stab >= 0.70:
        for k, d in (
            ("countermeasure_invest", 0.045),
            ("damper_bias", 0.03),
            ("viscosity_bias", 0.025),
            ("failure_respect", 0.03),
            ("pairing_strength", 0.02),
        ):
            old = float(paradox.intuition.get(k, 1.0))
            paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))
    if meta["first_hard_break"] is not None:
        for k, d in (("damper_bias", 0.035), ("repair_bias", 0.02), ("explore_bias", -0.015)):
            old = float(paradox.intuition.get(k, 1.0 if k != "explore_bias" else 0.3))
            if k == "explore_bias":
                paradox.intuition[k] = float(np.clip(old + d, 0.05, 0.6))
            else:
                paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))
    # slight repair if recovered late after peaks
    if late >= TARGET - 0.05 and high_stab >= 0.68:
        old = float(paradox.intuition.get("repair_bias", 1.0))
        paradox.intuition["repair_bias"] = float(np.clip(old + 0.02, 0.05, 2.5))

    return {
        "cycle": cycle,
        "seed": seed,
        "late": late,
        "min": float(np.min(arr)),
        "mean": float(np.mean(arr)),
        "edge": edge_coh(agents),
        "high_I_stab": high_stab,
        "mean_shield": float(np.mean(shield_series)),
        "peak_I": peak_I,
        "scar_n": report.get("n_scars", len(scars)),
        "intuition": {
            k: float(paradox.intuition[k])
            for k in (
                "damper_bias",
                "repair_bias",
                "viscosity_bias",
                "explore_bias",
                "countermeasure_invest",
                "failure_respect",
                "pairing_strength",
            )
            if k in paradox.intuition
        },
        "stab_series": stab_series,
        "I_series": I_sched,
        "shield_series": shield_series,
    }


def toughen_paradox(seed: int, shell: StormShell) -> tuple[K.Paradox, list]:
    """3 toughen cycles → return learned Paradox + cycle logs."""
    paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
    logs = []
    for c in range(1, N_TOUGHEN_CYCLES + 1):
        log = run_toughen_cycle(cycle=c, seed=seed, paradox=paradox, shell=shell, steps=160)
        logs.append(log)
        print(
            f"    toughen seed={seed} c{c}  late={log['late']:.3f}  "
            f"highI={log['high_I_stab']:.3f}  min={log['min']:.3f}  "
            f"cm={log['intuition'].get('countermeasure_invest', 0):.3f}  "
            f"damp={log['intuition'].get('damper_bias', 0):.3f}"
        )
    return paradox, logs


# ---------------------------------------------------------------------------
# Eval: reuse hell harness scenarios with custom paradox DNA + shell
# ---------------------------------------------------------------------------
def run_eval_episode(
    *,
    scenario: str,
    seed: int,
    dna_intuition: dict,
    use_shell: bool,
    steps: int = 100,
) -> dict:
    """Single eval episode using hell_beacons scenario + optional shell + custom intuition."""
    # Build a Paradox with promoted base + overridden intuition
    dna = copy.deepcopy(K.PROMOTED_DNA)
    dna["intuition"] = {**dna["intuition"], **{k: float(v) for k, v in dna_intuition.items()}}
    dna["intuition"]["target_coherence"] = TARGET

    # Use hell harness episode path but inject DNA via stack baseline + manual
    # Easier: local loop mirroring H.run_episode with custom paradox
    meta = H.SCENARIOS[scenario]
    fn = meta["fn"]
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

    paradox = K.Paradox(dna)
    paradox.install_drivers(agents)
    shell = StormShell(enabled=use_shell, beacons=use_shell)
    cm = float(paradox.intuition.get("countermeasure_invest", 0.5))

    stab_series = []
    I_series = []
    ambient = 0.0
    I = 1.5
    prev_I = 1.5
    prev_stab = 0.55
    prev_prev = 0.55

    for t in range(steps):
        I = float(fn(t, steps, rng, I))
        I_series.append(I)
        dI = I - prev_I
        dS = prev_stab - prev_prev
        if use_shell:
            scale = shell.scale(I, prev_stab, dI, dS, countermeasure=cm)
        else:
            scale = 1.0
        felt = I * scale

        for a in agents:
            a.step(felt, ambient, rng)
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
        if use_shell:
            shell.aftermath(agents, I, scale)
            shell.beacons_pull(agents, I)

        for a in agents:
            tc = a.instinct.get("target_coherence", TARGET)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        if use_hive:
            paradox.hive_pair_churn(agents, rng)
        if paradox_tight:
            paradox.install_drivers(agents)
            paradox.install_drivers(agents)
        else:
            paradox.install_drivers(agents)

        stab = K.stability(agents)
        stab_series.append(stab)
        prev_I = I
        prev_prev = prev_stab
        prev_stab = stab

    arr = np.array(stab_series)
    late_n = max(1, steps // 5)
    late = float(np.mean(arr[-late_n:]))
    hell_slice = arr[8:55] if len(arr) > 55 else arr
    edge = edge_coh(agents)
    hard = late < HARD_LATE or float(np.min(arr)) < HARD_MIN
    soft = (not hard) and (late < SOFT_LATE or edge < 0.55)
    return {
        "scenario": scenario,
        "seed": seed,
        "late": late,
        "min": float(np.min(arr)),
        "hell_min": float(np.min(hell_slice)),
        "edge": edge,
        "hard": hard,
        "soft": soft,
        "mean_I": float(np.mean(I_series)),
        "max_I": float(np.max(I_series)),
    }


def agg_eval(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "late_mean": float(np.mean([r["late"] for r in rows])),
        "late_std": float(np.std([r["late"] for r in rows])),
        "min_mean": float(np.mean([r["min"] for r in rows])),
        "hell_min_mean": float(np.mean([r["hell_min"] for r in rows])),
        "edge_mean": float(np.mean([r["edge"] for r in rows])),
        "hard_rate": float(np.mean([r["hard"] for r in rows])),
        "soft_rate": float(np.mean([r["soft"] for r in rows])),
        "hold_rate": float(np.mean([not r["hard"] and not r["soft"] for r in rows])),
    }


def main() -> int:
    print("=" * 72)
    print(" TOUGHEN 3.0↔6.4 × 3 cycles → HELL INCARNATE EVAL")
    print("=" * 72)

    shell = StormShell(enabled=True, beacons=True)
    promoted_int = {
        k: float(v)
        for k, v in K.PROMOTED_DNA["intuition"].items()
        if isinstance(v, (int, float))
    }

    # --- TRAIN: average learned intuition across seeds (or eval per-seed) ---
    print("\n[1] TOUGHEN TRAINING (3 cycles × seeds, shell ON)")
    all_train_logs = []
    learned_by_seed: dict[int, dict] = {}
    for seed in TRAIN_SEEDS:
        print(f"  --- seed {seed} ---")
        px, logs = toughen_paradox(seed, copy.deepcopy(shell))
        all_train_logs.extend(logs)
        learned_by_seed[seed] = {
            k: float(px.intuition[k])
            for k in promoted_int
            if k in px.intuition and isinstance(px.intuition[k], (int, float))
        }
        # ensure target locked
        learned_by_seed[seed]["target_coherence"] = TARGET

    # mean learned intuition (ensemble toughen)
    mean_learned = {}
    for k in promoted_int:
        vals = [learned_by_seed[s][k] for s in TRAIN_SEEDS if k in learned_by_seed[s]]
        if vals:
            mean_learned[k] = float(np.mean(vals))
    mean_learned["target_coherence"] = TARGET

    print("\n  Mean intuition after toughen (vs promoted):")
    for k in (
        "damper_bias",
        "repair_bias",
        "viscosity_bias",
        "explore_bias",
        "countermeasure_invest",
        "failure_respect",
        "pairing_strength",
    ):
        if k in mean_learned:
            print(f"    {k:24s}  {promoted_int.get(k, 0):.3f} → {mean_learned[k]:.3f}")

    train_c1 = [L for L in all_train_logs if L["cycle"] == 1]
    train_c3 = [L for L in all_train_logs if L["cycle"] == 3]
    print(
        f"\n  Toughen high-I stab: c1={np.mean([x['high_I_stab'] for x in train_c1]):.3f}  "
        f"c3={np.mean([x['high_I_stab'] for x in train_c3]):.3f}  "
        f"Δ={np.mean([x['high_I_stab'] for x in train_c3]) - np.mean([x['high_I_stab'] for x in train_c1]):+.3f}"
    )
    print(
        f"  Toughen late:        c1={np.mean([x['late'] for x in train_c1]):.3f}  "
        f"c3={np.mean([x['late'] for x in train_c3]):.3f}  "
        f"Δ={np.mean([x['late'] for x in train_c3]) - np.mean([x['late'] for x in train_c1]):+.3f}"
    )

    # --- EVAL arms ---
    # Also register annihilation-like via beyond + hell; use same scenarios as before
    eval_scenarios = [
        "mild",
        "cruel",
        "hell_incarnate",
        "flicker",
        "noise_flood",
        "beyond_map",
        "hell_no_hive",
        "hell_solo_paradox",
    ]

    arms = {
        "A_base_noshell": {"intuition": promoted_int, "shell": False},
        "B_shell_promoted": {"intuition": promoted_int, "shell": True},
        "C_shell_toughened": {"intuition": mean_learned, "shell": True},
        "D_toughened_noshell": {"intuition": mean_learned, "shell": False},
    }

    # Per-seed toughen eval (fairer): C/D use that seed's learned DNA
    print("\n[2] HELL EVAL MATRIX")
    matrix = {arm: {} for arm in arms}
    detail_rows = []

    for arm_name, cfg in arms.items():
        print(f"\n  ### {arm_name}")
        for scen in eval_scenarios:
            rows = []
            for seed in EVAL_SEEDS:
                if arm_name in ("C_shell_toughened", "D_toughened_noshell"):
                    intu = learned_by_seed[seed]
                else:
                    intu = cfg["intuition"]
                r = run_eval_episode(
                    scenario=scen,
                    seed=seed,
                    dna_intuition=intu,
                    use_shell=cfg["shell"],
                    steps=100,
                )
                rows.append(r)
                detail_rows.append({"arm": arm_name, **r})
            a = agg_eval(rows)
            matrix[arm_name][scen] = a
            print(
                f"    {scen:18s} late={a['late_mean']:.3f} min={a['min_mean']:.3f} "
                f"edge={a['edge_mean']:.3f} hard%={100*a['hard_rate']:.0f} "
                f"hold%={100*a['hold_rate']:.0f}"
            )

    # --- Comparison table: B vs C (shell same, toughen?) and A vs D ---
    print("\n" + "=" * 72)
    print(" IMPROVEMENT TABLE (late stab)")
    print("=" * 72)
    print(
        f"{'scenario':18s}  {'A base':>7s}  {'B shell':>7s}  {'C t+sh':>7s}  "
        f"{'D t only':>7s}  {'C−B':>7s}  {'C−A':>7s}  {'D−A':>7s}"
    )
    improvements = {}
    for scen in eval_scenarios:
        A = matrix["A_base_noshell"][scen]["late_mean"]
        B = matrix["B_shell_promoted"][scen]["late_mean"]
        C = matrix["C_shell_toughened"][scen]["late_mean"]
        D = matrix["D_toughened_noshell"][scen]["late_mean"]
        improvements[scen] = {
            "A": A,
            "B": B,
            "C": C,
            "D": D,
            "C_minus_B": C - B,
            "C_minus_A": C - A,
            "D_minus_A": D - A,
            "B_minus_A": B - A,
        }
        print(
            f"{scen:18s}  {A:7.3f}  {B:7.3f}  {C:7.3f}  {D:7.3f}  "
            f"{C-B:+7.3f}  {C-A:+7.3f}  {D-A:+7.3f}"
        )

    # Aggregate lift
    def mean_key(arm_scen_key):
        return float(np.mean([improvements[s][arm_scen_key] for s in eval_scenarios]))

    print("\n[AGGREGATE late across scenarios]")
    print(f"  mean C−B (toughen given shell): {mean_key('C_minus_B'):+.4f}")
    print(f"  mean C−A (full stack vs base):  {mean_key('C_minus_A'):+.4f}")
    print(f"  mean B−A (shell alone):         {mean_key('B_minus_A'):+.4f}")
    print(f"  mean D−A (toughen instincts only): {mean_key('D_minus_A'):+.4f}")

    hell_lift = improvements["hell_incarnate"]["C_minus_B"]
    beyond_lift = improvements["beyond_map"]["C_minus_B"]
    print(f"\n  hell_incarnate C−B: {hell_lift:+.4f}")
    print(f"  beyond_map     C−B: {beyond_lift:+.4f}")

    if mean_key("C_minus_B") > 0.01:
        verdict = (
            "TOUGHEN HELPS: 3.0↔6.4 training improves hell eval beyond shell alone."
        )
    elif mean_key("C_minus_B") > 0.003:
        verdict = (
            "TOUGHEN MARGINAL: small transfer on top of shell; shell still main lever."
        )
    elif mean_key("B_minus_A") > 0.02 and mean_key("D_minus_A") > 0.005:
        verdict = (
            "SPLIT: shell dominates hell eval; toughen helps without shell (instincts)."
        )
    elif mean_key("B_minus_A") > 0.02:
        verdict = (
            "SHELL DOMINATES: toughen train interesting, little extra on hell suite."
        )
    else:
        verdict = "NO CLEAR TRANSFER: inspect per-scenario."

    print(f"\n  VERDICT → {verdict}")

    # plots
    fig, axes = plt.subplots(2, 1, figsize=(11, 8))
    ax = axes[0]
    x = np.arange(len(eval_scenarios))
    w = 0.2
    for i, (arm, col) in enumerate(
        [
            ("A_base_noshell", "#888"),
            ("B_shell_promoted", "#3498db"),
            ("C_shell_toughened", "#2ecc71"),
            ("D_toughened_noshell", "#e67e22"),
        ]
    ):
        ys = [matrix[arm][s]["late_mean"] for s in eval_scenarios]
        ax.bar(x + (i - 1.5) * w, ys, w, label=arm, color=col)
    ax.axhline(TARGET, color="#2980b9", ls="--", lw=1)
    ax.axhline(HARD_LATE, color="#c0392b", ls=":", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(eval_scenarios, rotation=25, ha="right", fontsize=8)
    ax.set_ylabel("late stability")
    ax.set_title("Hell eval after 3.0↔6.4 toughen × 3")
    ax.legend(fontsize=7)
    ax.set_ylim(0.5, 1.02)
    ax.grid(True, alpha=0.25, axis="y")

    # toughen trajectory seed 42
    ax2 = axes[1]
    # re-run one toughen series for plot from logs
    s42 = [L for L in all_train_logs if L["seed"] == 42]
    if s42:
        # show last cycle I and stab
        last = s42[-1]
        ax2.plot(last["I_series"], label="I (3→6.4 ramps)", color="#e74c3c", alpha=0.75, lw=1)
        ax2b = ax2.twinx()
        ax2b.plot(last["stab_series"], label="stab c3", color="#2ecc71", lw=1.5)
        if s42[0].get("stab_series"):
            ax2b.plot(s42[0]["stab_series"], label="stab c1", color="#888", lw=1.0, alpha=0.8)
        ax2b.set_ylabel("stability")
        ax2b.set_ylim(0.3, 1.02)
        ax2b.legend(loc="lower right", fontsize=8)
    ax2.set_xlabel("step")
    ax2.set_ylabel("I")
    ax2.set_title("Toughen cycle (seed=42): I schedule + stab c1 vs c3")
    ax2.grid(True, alpha=0.25)
    fig.tight_layout()
    png = OUT / "toughen_then_hell_eval.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # cliff ladder style B vs C
    ladder = ["mild", "cruel", "hell_incarnate", "beyond_map"]
    fig2, ax3 = plt.subplots(figsize=(9, 5))
    for arm, col in [
        ("A_base_noshell", "#888"),
        ("B_shell_promoted", "#3498db"),
        ("C_shell_toughened", "#2ecc71"),
        ("D_toughened_noshell", "#e67e22"),
    ]:
        ys = [matrix[arm][s]["late_mean"] for s in ladder]
        ax3.plot(ladder, ys, "o-", color=col, lw=2, label=arm)
    ax3.axhline(TARGET, ls="--", color="#2980b9")
    ax3.set_ylabel("late stab")
    ax3.set_title("Cliff ladder: base / shell / toughened")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)
    fig2.tight_layout()
    png2 = OUT / "toughen_cliff_ladder.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "toughen_3_0_to_6_4_then_hell_eval",
        "n_toughen_cycles": N_TOUGHEN_CYCLES,
        "train_seeds": TRAIN_SEEDS,
        "mean_learned_intuition": mean_learned,
        "promoted_intuition": promoted_int,
        "toughen_c1_high_I": float(np.mean([x["high_I_stab"] for x in train_c1])),
        "toughen_c3_high_I": float(np.mean([x["high_I_stab"] for x in train_c3])),
        "toughen_c1_late": float(np.mean([x["late"] for x in train_c1])),
        "toughen_c3_late": float(np.mean([x["late"] for x in train_c3])),
        "eval_matrix": matrix,
        "improvements": improvements,
        "aggregate": {
            "mean_C_minus_B": mean_key("C_minus_B"),
            "mean_C_minus_A": mean_key("C_minus_A"),
            "mean_B_minus_A": mean_key("B_minus_A"),
            "mean_D_minus_A": mean_key("D_minus_A"),
            "hell_C_minus_B": hell_lift,
            "beyond_C_minus_B": beyond_lift,
        },
        "verdict": verdict,
        "note": "Soft Pack DNA not promoted; toughen is experimental Paradox intuition only",
    }
    js = OUT / "toughen_then_hell_eval.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
