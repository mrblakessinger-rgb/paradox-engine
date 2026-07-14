"""
Storm Surge Shell v2 — tune + 3-cycle learn under insane conditions
===================================================================
1) Tightened SURGE SHIELD (storm shell):
   - smoother engage curve (not binary floor slam)
   - predictive: rising I + falling stab → arm early
   - recovery handoff: when I drops, release shield so swarm can climb
   - dead-fleet limp mode: weak shield if stab already collapsed (no fake immortality)
   - Paradox countermeasure_invest slightly deepens max cut (learned)

2) Optional beacons (edge → core) under high I

3) Three full sim CYCLES — same hell gauntlet each cycle:
   Cycle N → scars → Paradox.compress → install into next cycle's swarm
   Compare cycle1 vs cycle2 vs cycle3 (does the swarm *learn* to cope?)

4) Control arm: frozen intuition (no compress) × 3 cycles
   Separates learning from "we got lucky seeds."

DNA start: PROMOTED. Learning is episode-local Paradox intuition — NOT Soft Pack promote.

  python real_world/storm_surge_learn_cycles.py
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
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

TARGET = 0.92
CEILING = K.CEILING_SOFT
HARD_LATE = 0.70
HARD_MIN = 0.35
SOFT_LATE = 0.85
N_CYCLES = 3


# ---------------------------------------------------------------------------
# Tuned storm surge shell v2
# ---------------------------------------------------------------------------
@dataclass
class StormShell:
    """Tightened surge shield — the storm shell add-on."""

    enabled: bool = True
    beacons: bool = True
    # engage
    I_arm: float = 1.55  # earlier than v1 1.8 — predictive room
    I_full: float = 3.4  # full cut depth by here
    max_cut: float = 0.48  # slightly stronger than 0.42
    # limp: if stab very low, don't pretend
    limp_stab: float = 0.42
    limp_cut_scale: float = 0.45
    # aftermath flux damp
    flux_clip: float = 0.50
    # predictive
    dI_arm: float = 0.12  # rising I boosts cut
    dS_arm: float = -0.02  # falling stab boosts cut
    # recovery handoff
    release_I: float = 1.85
    release_boost: float = 0.12  # add back to scale (weaker shield) when calm+ok
    # beacons
    beacon_I_on: float = 2.1
    n_beacons: int = 6
    beacon_pull: float = 0.16
    beacon_flux_damp: float = 0.88
    edge_frac: float = 0.24

    def scale(
        self,
        I: float,
        stab: float,
        dI: float,
        dS: float,
        *,
        countermeasure: float = 0.5,
    ) -> float:
        if not self.enabled:
            return 1.0
        # countermeasure_invest (0.05–2.5) → slight deepen of max cut
        cm = float(np.clip(countermeasure, 0.2, 2.0))
        max_cut = self.max_cut * (0.88 + 0.14 * min(cm, 1.5))

        if I < self.I_arm and dI < self.dI_arm:
            return 1.0

        # depth 0..1 along I
        depth = float(np.clip((I - self.I_arm) / max(self.I_full - self.I_arm, 1e-6), 0, 1))
        # smoothstep
        depth = depth * depth * (3.0 - 2.0 * depth)

        # hold: need residual coherence
        hold = float(np.clip((stab - 0.35) / 0.55, 0, 1))

        # predictive boosts
        pred = 0.0
        if dI >= self.dI_arm:
            pred += 0.12 * min(1.0, dI / 0.4)
        if dS <= self.dS_arm:
            pred += 0.10 * min(1.0, abs(dS) / 0.05)

        cut = max_cut * depth * (0.30 + 0.70 * hold) * (1.0 + pred)
        cut = float(np.clip(cut, 0.0, max_cut))

        # limp mode — shell almost down if fleet already smashed
        if stab < self.limp_stab:
            cut *= self.limp_cut_scale

        scale = 1.0 - cut

        # recovery handoff: calm I + healthy stab → open shell
        if I < self.release_I and stab >= TARGET - 0.06:
            scale = min(1.0, scale + self.release_boost)

        return float(np.clip(scale, 1.0 - max_cut, 1.0))

    def aftermath(self, agents, I: float, scale: float) -> None:
        if not self.enabled or scale >= 0.985:
            return
        strength = (1.0 - scale) / max(self.max_cut, 1e-6)
        damp = 1.0 - (1.0 - self.flux_clip) * strength * min(1.2, I / 3.2)
        damp = float(np.clip(damp, 0.42, 1.0))
        for a in agents:
            a.flux *= damp
            a.velocity *= 0.48 + 0.52 * damp

    def beacons_pull(self, agents, I: float) -> int:
        if not self.beacons or I < self.beacon_I_on:
            return 0
        n = len(agents)
        order = np.argsort([a.coherence for a in agents])
        n_edge = max(1, int(round(n * self.edge_frac)))
        edge = [int(i) for i in order[:n_edge]]
        beac = [int(i) for i in order[-self.n_beacons :]]
        core = float(np.mean([agents[i].coherence for i in beac]))
        intensity = float(np.clip((I - self.beacon_I_on) / 2.2, 0, 1.3))
        pull = self.beacon_pull * (0.5 + 0.5 * intensity)
        for i in edge:
            a = agents[i]
            a.coherence = float(
                np.clip(
                    (1.0 - pull) * a.coherence + pull * core + 0.025 * (TARGET - a.coherence),
                    0,
                    CEILING,
                )
            )
            a.flux = float(np.clip(a.flux * self.beacon_flux_damp, -2.5, 2.5))
            a.velocity *= 0.91
        tax = 0.007 * intensity
        for i in beac:
            agents[i].coherence = float(np.clip(agents[i].coherence - tax, 0, CEILING))
        return len(edge)


# ---------------------------------------------------------------------------
# Gauntlet (insane conditions — one "cycle" = full tour)
# ---------------------------------------------------------------------------
def I_phase(t: int, phase: str, rng: np.random.Generator, I: float) -> float:
    if phase == "warm":
        return float(np.clip(1.2 + rng.normal(0, 0.06), 0.7, 1.8))
    if phase == "cruel":
        return float(np.clip(2.8 + rng.normal(0, 0.08), 2.4, 3.1))
    if phase == "hell":
        return float(np.clip(3.7 + rng.normal(0, 0.18), 3.2, 4.4))
    if phase == "flicker":
        return float(rng.choice([0.8, 1.5, 2.5, 3.5, 4.5, 5.0]))
    if phase == "beyond":
        return float(np.clip(5.0 + rng.normal(0, 0.35), 4.3, 6.0))
    if phase == "annihilate":
        return float(np.clip(7.0 + rng.normal(0, 0.45), 6.0, 8.5))
    if phase == "recover":
        return float(np.clip(1.4 + rng.normal(0, 0.12), 0.8, 2.2))
    return float(np.clip(I + rng.normal(0, 0.1), 0.5, 6.0))


# One cycle: fixed phase schedule (steps)
PHASE_PLAN = [
    ("warm", 12),
    ("cruel", 18),
    ("hell", 22),
    ("flicker", 16),
    ("beyond", 18),
    ("annihilate", 14),
    ("recover", 20),
]
# total steps = sum of durations
CYCLE_STEPS = sum(d for _, d in PHASE_PLAN)


def phase_at(t: int) -> str:
    acc = 0
    for name, dur in PHASE_PLAN:
        acc += dur
        if t < acc:
            return name
    return PHASE_PLAN[-1][0]


@dataclass
class CycleMetrics:
    cycle: int
    learn: bool
    shell: bool
    seed: int
    late_stab: float
    mean_stab: float
    min_stab: float
    edge_final: float
    hard: bool
    soft: bool
    mean_shield: float
    phase_late: dict = field(default_factory=dict)
    scar_n: int = 0
    wisdom_keys: list = field(default_factory=list)
    intuition_snap: dict = field(default_factory=dict)
    stab_series: list = field(default_factory=list)
    I_series: list = field(default_factory=list)
    shield_series: list = field(default_factory=list)


def edge_coh(agents) -> float:
    order = np.argsort([a.coherence for a in agents])
    n = max(1, int(0.2 * len(agents)))
    return float(np.mean([agents[int(i)].coherence for i in order[:n]]))


def run_cycle(
    *,
    cycle: int,
    seed: int,
    paradox: K.Paradox,
    shell: StormShell | None,
    learn: bool,
    steps: int = CYCLE_STEPS,
) -> tuple[CycleMetrics, list, dict]:
    """
    Run one full gauntlet. Returns metrics, scars list, episode_meta.
    Paradox state persists across cycles when learn=True (caller reuses object).
    """
    rng = np.random.default_rng(seed + cycle * 1009)
    agents = K.make_swarm(rng)
    # harsher start each cycle slightly — still learnable
    hurt = 0.10 + 0.03 * (cycle - 1)
    for a in agents:
        a.coherence = float(
            np.clip(a.coherence * (1.0 - hurt) + rng.uniform(-0.05, 0.02), 0.12, 0.68)
        )
        a.flux += float(rng.normal(0, 0.15 + 0.05 * cycle))

    paradox.install_drivers(agents)
    cm = float(paradox.intuition.get("countermeasure_invest", 0.5))

    stab_series = []
    I_series = []
    shield_series = []
    phase_stabs: dict[str, list] = {p: [] for p, _ in PHASE_PLAN}
    scars = []
    ambient = 0.0
    I = 1.2
    prev_I = 1.2
    prev_stab = 0.55
    prev_prev_stab = 0.55
    first_soft = None
    first_hard = None
    recovery_peak = 0.0

    for t in range(steps):
        phase = phase_at(t)
        I = I_phase(t, phase, rng, I)
        dI = I - prev_I
        dS = prev_stab - prev_prev_stab

        if shell and shell.enabled:
            scale = shell.scale(I, prev_stab, dI, dS, countermeasure=cm)
        else:
            scale = 1.0
        shield_series.append(scale)
        felt = I * scale

        # noise/shock scales with phase insanity
        noise_amp = {
            "warm": 1.0,
            "cruel": 1.2,
            "hell": 1.7,
            "flicker": 1.5,
            "beyond": 1.9,
            "annihilate": 2.8,
            "recover": 1.1,
        }[phase]
        shock = {
            "warm": 0.0,
            "cruel": 0.02,
            "hell": 0.06,
            "flicker": 0.05,
            "beyond": 0.09,
            "annihilate": 0.18,
            "recover": 0.01,
        }[phase]

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
                if shock > 0 and rng.random() < 0.14:
                    a.coherence = float(
                        np.clip(a.coherence - shock * rng.random() * (I / 4.0), 0, CEILING)
                    )

        if shell:
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
        I_series.append(I)
        phase_stabs[phase].append(stab)

        # scars for learning
        if t > 0 and stab < prev_stab - 0.025:
            scars.append({"reason": "tighten_storm", "I": I, "stab": stab, "phase": phase})
        if t > 0 and stab > prev_stab + 0.02 and I < 2.5:
            scars.append({"reason": "climb_recover", "I": I, "stab": stab, "phase": phase})
        if stab < SOFT_LATE and first_soft is None:
            first_soft = t
            scars.append({"reason": "soft_floor", "I": I, "stab": stab, "phase": phase})
        if (stab < HARD_LATE or stab < HARD_MIN) and first_hard is None:
            first_hard = t
            scars.append({"reason": "hard_break_threat", "I": I, "stab": stab, "phase": phase})
        # storm-specific scars
        if phase in ("hell", "beyond", "annihilate") and scale < 0.85:
            if t % 5 == 0:
                scars.append({"reason": "tighten_shell_active", "I": I, "scale": scale})
        if phase == "recover" and stab >= TARGET - 0.05:
            scars.append({"reason": "climb_calm", "I": I, "stab": stab})

        recovery_peak = max(recovery_peak, stab if phase == "recover" else recovery_peak)
        prev_I = I
        prev_prev_stab = prev_stab
        prev_stab = stab

    arr = np.array(stab_series)
    late_n = max(1, steps // 6)
    late = float(np.mean(arr[-late_n:]))
    # recover phase late specifically
    rec = phase_stabs.get("recover") or [late]
    phase_late = {p: float(np.mean(v[-max(1, len(v) // 3) :])) if v else 0.0 for p, v in phase_stabs.items()}

    hard = late < HARD_LATE or float(np.min(arr)) < HARD_MIN
    soft = (not hard) and (late < SOFT_LATE or edge_coh(agents) < 0.55)

    meta = {
        "final_alive": late >= HARD_LATE,
        "first_soft_break": first_soft,
        "first_hard_break": first_hard if hard else None,
        "recovery_peak": float(max(rec)),
        "recovery_late": float(np.mean(rec[-max(1, len(rec) // 3) :])),
        "survived_long_hell": first_hard is None and phase_late.get("hell", 0) > 0.75,
        "cycle": cycle,
        "mean_I": float(np.mean(I_series)),
        "min_stab": float(np.min(arr)),
    }

    # cap scars
    if len(scars) > 80:
        scars = scars[-80:]

    m = CycleMetrics(
        cycle=cycle,
        learn=learn,
        shell=bool(shell and shell.enabled),
        seed=seed,
        late_stab=late,
        mean_stab=float(np.mean(arr)),
        min_stab=float(np.min(arr)),
        edge_final=edge_coh(agents),
        hard=hard,
        soft=soft,
        mean_shield=float(np.mean(shield_series)),
        phase_late=phase_late,
        scar_n=len(scars),
        stab_series=stab_series,
        I_series=I_series,
        shield_series=shield_series,
    )
    return m, scars, meta


def run_arm(
    *,
    name: str,
    seeds: list[int],
    shell: StormShell | None,
    learn: bool,
    max_delta: float = 0.07,
) -> dict:
    """
    For each seed: 3 cycles sharing one Paradox (learning) or reset (frozen).
    """
    print(f"\n{'='*64}\n ARM: {name}  learn={learn}  shell={shell.enabled if shell else False}\n{'='*64}")
    by_cycle: dict[int, list[CycleMetrics]] = {1: [], 2: [], 3: []}
    intuition_trace = []

    for seed in seeds:
        if learn:
            paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
        for c in range(1, N_CYCLES + 1):
            if not learn:
                paradox = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
            m, scars, meta = run_cycle(
                cycle=c, seed=seed, paradox=paradox, shell=shell, learn=learn
            )
            if learn:
                paradox.absorb_episode(scars, episode_meta=meta)
                # storm-specific wisdom hooks via scar reasons already mapped
                # boost climb scars count for recovery learning
                report = paradox.compress_scars_to_wisdom(max_intuition_delta=max_delta)
                # extra storm shell learning: if survived hell phases, invest countermeasure
                if meta.get("survived_long_hell") or (
                    meta.get("recovery_late") is not None and float(meta["recovery_late"]) >= 0.80
                ):
                    old = float(paradox.intuition.get("countermeasure_invest", 0.5))
                    paradox.intuition["countermeasure_invest"] = float(
                        np.clip(old + 0.035, 0.05, 2.2)
                    )
                if meta.get("first_hard_break") is not None:
                    # learned respect for floor — damper up slightly
                    for k, d in (("damper_bias", 0.025), ("viscosity_bias", 0.02), ("failure_respect", 0.03)):
                        old = float(paradox.intuition.get(k, 1.0))
                        paradox.intuition[k] = float(np.clip(old + d, 0.05, 2.5))
                m.wisdom_keys = list((paradox.wisdom or {}).keys())
                m.intuition_snap = {
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
                }
                m.scar_n = report.get("n_scars", m.scar_n)
            by_cycle[c].append(m)
            tag = "HARD" if m.hard else ("SOFT" if m.soft else "HOLD")
            print(
                f"  seed={seed} c{c}  late={m.late_stab:.3f} min={m.min_stab:.3f} "
                f"edge={m.edge_final:.3f} sh={m.mean_shield:.3f}  "
                f"hell={m.phase_late.get('hell',0):.3f} ann={m.phase_late.get('annihilate',0):.3f} "
                f"rec={m.phase_late.get('recover',0):.3f}  [{tag}]"
            )
        if learn:
            intuition_trace.append(m.intuition_snap)

    summary = {}
    for c in range(1, N_CYCLES + 1):
        rs = by_cycle[c]
        summary[c] = {
            "late_mean": float(np.mean([r.late_stab for r in rs])),
            "late_std": float(np.std([r.late_stab for r in rs])),
            "min_mean": float(np.mean([r.min_stab for r in rs])),
            "edge_mean": float(np.mean([r.edge_final for r in rs])),
            "hard_rate": float(np.mean([r.hard for r in rs])),
            "soft_rate": float(np.mean([r.soft for r in rs])),
            "hold_rate": float(np.mean([not r.hard and not r.soft for r in rs])),
            "mean_shield": float(np.mean([r.mean_shield for r in rs])),
            "phase_late": {
                p: float(np.mean([r.phase_late.get(p, 0) for r in rs]))
                for p, _ in PHASE_PLAN
            },
        }
        print(
            f"  CYCLE {c} Σ  late={summary[c]['late_mean']:.3f}±{summary[c]['late_std']:.3f}  "
            f"min={summary[c]['min_mean']:.3f} edge={summary[c]['edge_mean']:.3f}  "
            f"hard%={100*summary[c]['hard_rate']:.0f} hold%={100*summary[c]['hold_rate']:.0f}"
        )

    d13 = summary[3]["late_mean"] - summary[1]["late_mean"]
    print(f"  Δ late c3−c1 = {d13:+.4f}")
    return {
        "name": name,
        "learn": learn,
        "shell": bool(shell and shell.enabled) if shell else False,
        "by_cycle": summary,
        "delta_c3_c1": d13,
        "intuition_trace_last": intuition_trace,
        "raw_cycles": {
            c: [
                {
                    "seed": r.seed,
                    "late": r.late_stab,
                    "min": r.min_stab,
                    "edge": r.edge_final,
                    "hard": r.hard,
                    "soft": r.soft,
                    "phase_late": r.phase_late,
                    "mean_shield": r.mean_shield,
                    "intuition": r.intuition_snap,
                }
                for r in by_cycle[c]
            ]
            for c in range(1, N_CYCLES + 1)
        },
        # keep one series for plot (seed mid)
        "plot_series": {
            "c1": by_cycle[1][len(seeds) // 2].stab_series if by_cycle[1] else [],
            "c3": by_cycle[3][len(seeds) // 2].stab_series if by_cycle[3] else [],
            "I": by_cycle[1][len(seeds) // 2].I_series if by_cycle[1] else [],
            "shield_c3": by_cycle[3][len(seeds) // 2].shield_series if by_cycle[3] else [],
        },
    }


def main() -> int:
    print("=" * 72)
    print(" STORM SURGE SHELL v2 + 3-CYCLE LEARN (insane gauntlet)")
    print(f" steps/cycle={CYCLE_STEPS}  phases={[p for p,_ in PHASE_PLAN]}")
    print(" DNA start: PROMOTED · no Soft Pack promote · scars → Paradox only")
    print("=" * 72)

    seeds = [7, 21, 42, 99]

    shell_v2 = StormShell(enabled=True, beacons=True)
    shell_surge_only = StormShell(enabled=True, beacons=False)

    arms = [
        run_arm(name="baseline_no_shell_frozen", seeds=seeds, shell=None, learn=False),
        run_arm(
            name="shell_v2_frozen",
            seeds=seeds,
            shell=copy.deepcopy(shell_v2),
            learn=False,
        ),
        run_arm(
            name="shell_v2_LEARN",
            seeds=seeds,
            shell=copy.deepcopy(shell_v2),
            learn=True,
            max_delta=0.07,
        ),
        run_arm(
            name="surge_only_LEARN",
            seeds=seeds,
            shell=copy.deepcopy(shell_surge_only),
            learn=True,
            max_delta=0.07,
        ),
    ]

    print("\n" + "=" * 72)
    print(" CROSS-ARM: late stab by cycle")
    print("=" * 72)
    print(f"{'arm':28s}  c1      c2      c3     Δc3-c1  hard%c3")
    for a in arms:
        s = a["by_cycle"]
        print(
            f"{a['name']:28s}  {s[1]['late_mean']:.3f}   {s[2]['late_mean']:.3f}   "
            f"{s[3]['late_mean']:.3f}  {a['delta_c3_c1']:+.4f}   {100*s[3]['hard_rate']:.0f}%"
        )

    # learning signal
    learn = next(a for a in arms if a["name"] == "shell_v2_LEARN")
    frozen = next(a for a in arms if a["name"] == "shell_v2_frozen")
    base = next(a for a in arms if a["name"] == "baseline_no_shell_frozen")

    print("\n[LEARNING vs SHELL vs BASELINE]")
    print(
        f"  baseline c3 late={base['by_cycle'][3]['late_mean']:.3f}  "
        f"hard%={100*base['by_cycle'][3]['hard_rate']:.0f}"
    )
    print(
        f"  shell frozen c3={frozen['by_cycle'][3]['late_mean']:.3f}  "
        f"Δ vs base={frozen['by_cycle'][3]['late_mean']-base['by_cycle'][3]['late_mean']:+.3f}"
    )
    print(
        f"  shell LEARN  c3={learn['by_cycle'][3]['late_mean']:.3f}  "
        f"Δ vs frozen={learn['by_cycle'][3]['late_mean']-frozen['by_cycle'][3]['late_mean']:+.3f}  "
        f"Δ c3−c1={learn['delta_c3_c1']:+.4f}"
    )

    # phase cope table for LEARN arm
    print("\n[PHASE COPE — shell_v2_LEARN phase late means]")
    print(f"  {'phase':12s}  c1      c2      c3")
    for p, _ in PHASE_PLAN:
        print(
            f"  {p:12s}  "
            f"{learn['by_cycle'][1]['phase_late'][p]:.3f}   "
            f"{learn['by_cycle'][2]['phase_late'][p]:.3f}   "
            f"{learn['by_cycle'][3]['phase_late'][p]:.3f}"
        )

    # verdict
    shell_helps = frozen["by_cycle"][3]["late_mean"] > base["by_cycle"][3]["late_mean"] + 0.03
    learns = learn["delta_c3_c1"] > 0.01
    learns_over_frozen = (
        learn["by_cycle"][3]["late_mean"] > frozen["by_cycle"][3]["late_mean"] + 0.008
    )
    if shell_helps and learns and learns_over_frozen:
        verdict = (
            "SHELL+LEARN: surge shell is a keeper; 3-cycle Paradox learning improves cope. "
            "Candidate storm-mode add-on (not second engine)."
        )
    elif shell_helps and not learns:
        verdict = (
            "SHELL_WINS_LEARN_FLAT: tightened shell carries the load; learning deltas small. "
            "Ship shell as actuate/storm skin; keep learn experimental."
        )
    elif shell_helps and learns and not learns_over_frozen:
        verdict = (
            "SHELL_PRIMARY: learning helps within arm but ≈ frozen shell — shell physics > scars. "
            "Tune shell; light Paradox nudges optional."
        )
    else:
        verdict = "MIXED: inspect phase table before wiring into product."

    print(f"\n  VERDICT → {verdict}")

    # plots
    fig, axes = plt.subplots(3, 1, figsize=(11, 10))
    # 1: late by cycle all arms
    ax = axes[0]
    x = np.array([1, 2, 3])
    for a, col, mk in zip(
        arms,
        ["#888", "#3498db", "#2ecc71", "#e67e22"],
        ["o", "s", "D", "^"],
    ):
        ys = [a["by_cycle"][c]["late_mean"] for c in (1, 2, 3)]
        ax.plot(x, ys, f"{mk}-", color=col, lw=2, label=a["name"])
    ax.axhline(TARGET, color="#2980b9", ls="--", lw=1)
    ax.axhline(HARD_LATE, color="#c0392b", ls=":", lw=1)
    ax.set_xticks(x)
    ax.set_xlabel("cycle")
    ax.set_ylabel("late stability")
    ax.set_title("3-cycle learn under insane gauntlet")
    ax.legend(fontsize=7, loc="best")
    ax.set_ylim(0.4, 1.02)
    ax.grid(True, alpha=0.25)

    # 2: one trajectory c1 vs c3 learn
    ax2 = axes[1]
    ps = learn["plot_series"]
    if ps["c1"]:
        ax2.plot(ps["c1"], label="LEARN c1 stab", color="#888", lw=1.2)
    if ps["c3"]:
        ax2.plot(ps["c3"], label="LEARN c3 stab", color="#2ecc71", lw=1.6)
    # phase bands
    acc = 0
    colors_p = {
        "warm": "#27ae60",
        "cruel": "#f39c12",
        "hell": "#e74c3c",
        "flicker": "#9b59b6",
        "beyond": "#c0392b",
        "annihilate": "#1a1a1a",
        "recover": "#3498db",
    }
    for name, dur in PHASE_PLAN:
        ax2.axvspan(acc, acc + dur, color=colors_p.get(name, "#ccc"), alpha=0.12)
        acc += dur
    ax2.set_ylabel("stability")
    ax2.set_title("LEARN arm trajectory (mid seed) c1 vs c3")
    ax2.legend(fontsize=8)
    ax2.set_ylim(0.0, 1.02)
    ax2.grid(True, alpha=0.25)

    # 3: shield scale c3 + I
    ax3 = axes[2]
    if ps["I"]:
        ax3.plot(ps["I"], label="I", color="#e74c3c", alpha=0.7, lw=1)
    if ps["shield_c3"]:
        ax3b = ax3.twinx()
        ax3b.plot(ps["shield_c3"], label="shield scale (felt mult)", color="#3498db", lw=1.5)
        ax3b.set_ylabel("shield scale", color="#3498db")
        ax3b.set_ylim(0.4, 1.05)
    ax3.set_xlabel("step")
    ax3.set_ylabel("I")
    ax3.set_title("Storm shell engagement (LEARN c3)")
    ax3.grid(True, alpha=0.25)

    fig.tight_layout()
    png = OUT / "storm_surge_learn_cycles.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "proto": "storm_surge_shell_v2_learn_3cycle",
        "cycle_steps": CYCLE_STEPS,
        "phases": PHASE_PLAN,
        "seeds": seeds,
        "n_cycles": N_CYCLES,
        "shell_v2_params": {
            "I_arm": shell_v2.I_arm,
            "I_full": shell_v2.I_full,
            "max_cut": shell_v2.max_cut,
            "flux_clip": shell_v2.flux_clip,
            "beacon_pull": shell_v2.beacon_pull,
        },
        "arms": [
            {
                "name": a["name"],
                "learn": a["learn"],
                "shell": a["shell"],
                "by_cycle": a["by_cycle"],
                "delta_c3_c1": a["delta_c3_c1"],
                "intuition_trace_last": a["intuition_trace_last"],
            }
            for a in arms
        ],
        "verdict": verdict,
        "notes": {
            "shell": "tightened engage/release/limp/predictive",
            "learn": "Paradox absorb scars → compress wisdom + countermeasure/damper nudges",
            "promote": "NO — Soft Pack DNA frozen",
        },
    }
    js = OUT / "storm_surge_learn_cycles.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
