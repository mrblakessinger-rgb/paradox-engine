#!/usr/bin/env python3
"""
================================================================================
  PARADOX / SWARM KERNEL  v1.0
  Single-file archive — save this to your hard drive.

  Status: PROMOTED DNA + multi-seed READY exam (S1–S11)
  Contract: target ~0.92 · anti-lock <0.97 · one-way Paradox · hive 5% churn

  Requires: Python 3.10+ and numpy
      pip install numpy

  Usage:
      python KERNEL_v1.py                  # status + short demo
      python KERNEL_v1.py --demo 80        # run N steps at variable I
      python KERNEL_v1.py --export-dna out.json
      python KERNEL_v1.py --status

  Architecture:
      Paradox  = aware of swarm + environment; installs instinct/wisdom
      Swarm    = NO memory of Paradox; acts on installed drivers only
      Hive     = each cycle: bottom 5% <-> mid 5%, then top 5% <-> new mid 5%
      L1 skin  = surge overflow downclock + residual turbulence
================================================================================
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# =============================================================================
# KERNEL CONTRACT (locked)
# =============================================================================
KERNEL_VERSION = "1.0"
KERNEL_STATUS = "PROMOTED_MULTI_SEED_READY"
TARGET_STABILITY = 0.92
CEILING_SOFT = 0.97
CEILING_HARD = 0.995
BAND_LO = 0.88
N_AGENTS = 100
PAIR_FRAC = 0.05
ONE_WAY_PARADOX = True

# =============================================================================
# PROMOTED DNA (exam-ready lineage — multi-seed READY)
# =============================================================================
PROMOTED_DNA: dict[str, Any] = {
    "kernel_version": "1.0",
    "kernel_status": "PROMOTED_MULTI_SEED_READY",
    "promoted_note": (
        "Multi-seed READY + Paradox reflection from quota-hell marathon "
        "(exam_reflected_dna PROMOTE 2026-07-12; swarm never saw raw scars)"
    ),
    "intuition": {
        "viscosity_bias": 2.0,
        "damper_bias": 2.16,
        "repair_bias": 2.03,
        "explore_bias": 0.10,
        "risk_aversion": 0.9,
        "coop_weight": 0.5,
        "predict_trust": 0.9,
        "target_coherence": 0.92,
        "failure_respect": 1.01,
        "challenge_caution": 0.4,
        "countermeasure_invest": 0.98,
        "pairing_strength": 0.94,
        "floor_boost": 0.15,
        "elite_share": 0.03,
    },
    # Compact high-value wisdom (training + Paradox-compressed episode scars)
    "wisdom_summary": {
        "high_I_hold": "stability≈0.92 under I≈2.8–3.0 with armor DNA",
        "anti_lock": "do not live at 1.0; soft ceiling 0.97",
        "jumps": "teleport between I spaces without collapse",
        "hive": "bottom5%↔mid5% then top5%↔new mid5%",
        "paradox": "one-way install; swarm never stores Paradox",
        "quota_budget_gate": "under saturated shared quota: cool thrash first; reopen only when budget funds attempts",
        "survive_before_goodput": "long continuous hell can keep fleet alive near target; low success floor expected until calm",
        "recovery_climb": "when env softens, reopen traffic and climb; recovery peaks real if cool held in hell",
        "soft_vs_hard_break": "soft break = utility floor under thrash; hard break = fleet death — do not confuse them",
        "paradox_scar_path": "raw episode scars absorbed by Paradox only; swarm receives instincts, not terror",
        "storm_arsenal": (
            "auto storm pack is in the arsenal for extreme env/thrash/budget/goodput spikes; "
            "engages without operator switch; releases after calm holds"
        ),
        "beacon_arsenal": (
            "when storm pack is active, beacons pull edge agents toward core; same latch as shell"
        ),
        "bright_path": (
            "success and recovery scars build competent optimism; trauma must not monopolize intuition"
        ),
        "damper_policy": (
            "Paradox owns live damper dial: up under storm/drill, ease in calm (band ~1.45–2.28)"
        ),
        "weekly_drill": (
            "once per week Paradox engages storm pack for arsenal practice (weekly_arsenal_drill)"
        ),
    },
}


def default_instinct() -> dict:
    return {
        "viscosity_bias": 1.0,
        "damper_bias": 1.0,
        "repair_bias": 1.0,
        "explore_bias": 0.45,
        "risk_aversion": 0.45,
        "coop_weight": 0.50,
        "predict_trust": 0.50,
        "target_coherence": TARGET_STABILITY,
    }


# =============================================================================
# SWARM MEMBER — no knowledge of Paradox
# =============================================================================
@dataclass
class SwarmMember:
    id: int
    coherence: float
    flux: float
    velocity: float
    instinct: dict
    last_pred: float = 0.5
    pred_error: float = 0.0
    performance: float = 0.0
    short_memory: list = field(default_factory=list)

    def predict_next(self, interference: float) -> float:
        I = self.instinct
        threat = interference * (1.0 - 0.4 * I["risk_aversion"])
        hope = I["repair_bias"] * 0.08 + I["damper_bias"] * 0.05
        explore = I["explore_bias"] * 0.04 * np.sin(self.id + interference)
        pred = self.coherence - 0.12 * threat + hope + explore
        trust = I["predict_trust"]
        self.last_pred = float(np.clip(trust * pred + (1 - trust) * self.coherence, 0, 1.2))
        return self.last_pred

    def step(self, interference: float, ambient: float, rng: np.random.Generator):
        """Act under installed instinct only."""
        I = self.instinct
        pred = self.predict_next(interference)
        noise = rng.normal(0, 0.04 + 0.10 * interference)
        surge = interference * 0.08 * rng.normal()
        risk = abs(self.flux) + (1.0 - self.coherence) + 0.3 * interference
        if risk > 0.85 + 0.4 * I["risk_aversion"]:
            # L1 residual: surge overflow downclock
            self.flux *= 0.35 * I["damper_bias"]
            self.coherence *= 0.55
            self.velocity *= 0.4

        target = I["target_coherence"]
        pull = 0.10 * I["repair_bias"] * (target - self.coherence)
        damp = 0.08 * I["damper_bias"] * self.velocity
        explore = I["explore_bias"] * 0.05 * rng.normal()
        self.velocity = (
            0.55 * self.velocity
            + pull
            - damp
            + noise
            + surge * (1.0 - 0.5 * I["viscosity_bias"])
            + explore
        )
        self.flux = float(np.clip(0.85 * self.flux + 0.15 * self.velocity + ambient, -2.5, 2.5))

        armor = max(
            0.85,
            0.55 * I["viscosity_bias"] + 0.55 * I["damper_bias"] + 0.35 * I["repair_bias"],
        )
        if interference >= 2.3:
            bleed = float(np.clip(0.04 * I["damper_bias"] + 0.02 * I["viscosity_bias"], 0.02, 0.18))
            self.flux *= 1.0 - bleed
            self.velocity *= 1.0 - 0.5 * bleed
        eff_I = float(interference / max(armor, 1e-6))
        local_order = 1.0 / (1.0 + abs(self.flux) * (0.45 + 0.35 * eff_I))
        alpha = float(np.clip(0.08 * I["repair_bias"] * min(I["viscosity_bias"], 2.0), 0.03, 0.32))
        rescue = 0.0
        if interference >= 2.0 and self.coherence < target:
            rescue = 0.06 * I["repair_bias"] * (target - self.coherence)
        if interference >= 2.5 and self.coherence < target:
            rescue += 0.05 * I["repair_bias"] * (target - self.coherence)
        self.coherence = float(
            np.clip((1 - alpha) * self.coherence + alpha * local_order + 0.55 * pull + rescue, 0, 1)
        )
        # soft anti-lock during live dynamics
        if self.coherence > CEILING_HARD:
            self.coherence = CEILING_SOFT - 0.01 * float(rng.random())

        self.pred_error = abs(self.coherence - pred)
        dist = abs(self.coherence - target)
        self.performance = float(
            np.clip(
                1.0 - 1.2 * dist - 0.5 * self.pred_error - 0.15 * min(1.0, abs(self.flux) / 2.0),
                0,
                1,
            )
        )
        self.short_memory.append({"coh": self.coherence, "perf": self.performance})
        if len(self.short_memory) > 12:
            self.short_memory = self.short_memory[-12:]


# =============================================================================
# PARADOX — aware of swarm + environment; swarm never stores this object
# =============================================================================
class Paradox:
    def __init__(self, dna: dict | None = None):
        self.intuition = default_instinct()
        self.intuition.update(
            {
                "failure_respect": 0.5,
                "pairing_strength": 0.55,
                "floor_boost": 0.04,
                "elite_share": 0.03,
                "countermeasure_invest": 0.5,
            }
        )
        self.wisdom: dict = {}
        self.cycle = 0
        self._raw_scars: list = []
        self._episode_meta: dict = {}
        if dna:
            self.load_dna(dna)

    def load_dna(self, dna: dict):
        if "intuition" in dna:
            for k, v in dna["intuition"].items():
                if isinstance(v, (int, float)):
                    self.intuition[k] = float(v)
        # Target stays on kernel contract unless dna explicitly sets it later
        self.intuition["target_coherence"] = TARGET_STABILITY
        if "wisdom_summary" in dna and isinstance(dna["wisdom_summary"], dict):
            self.wisdom = dict(dna["wisdom_summary"])
        # Episode scar buffer: raw trauma held only by Paradox, never by swarm
        self._raw_scars: list = []
        self._episode_meta: dict = {}

    def export_dna(self) -> dict:
        wisdom = dict(self.wisdom) if self.wisdom else dict(PROMOTED_DNA.get("wisdom_summary", {}))
        return {
            "kernel_version": KERNEL_VERSION,
            "kernel_status": KERNEL_STATUS,
            "intuition": {k: float(v) for k, v in self.intuition.items() if isinstance(v, (int, float))},
            "wisdom_summary": wisdom,
            "promoted_note": "Paradox-reflected DNA candidate — swarm never saw raw scars",
        }

    def absorb_episode(
        self,
        scars: list,
        *,
        episode_meta: dict | None = None,
    ) -> None:
        """
        Accept all raw episode scars without judgment.
        Swarm never receives this buffer. Compression is separate.
        """
        if not hasattr(self, "_raw_scars"):
            self._raw_scars = []
            self._episode_meta = {}
        # Cap buffer — Paradox compresses; it does not hoard infinite trauma
        self._raw_scars.extend(list(scars or []))
        if len(self._raw_scars) > 200:
            self._raw_scars = self._raw_scars[-200:]
        if episode_meta:
            self._episode_meta.update(episode_meta)

    def compress_scars_to_wisdom(self, *, max_intuition_delta: float = 0.06) -> dict:
        """
        Distill raw scars → wisdom_summary rules + tiny intuition nudges.
        No terror in the output: rules only, capped deltas, anti-lock safe.
        Returns report of what changed.
        """
        if not hasattr(self, "_raw_scars"):
            self._raw_scars = []
            self._episode_meta = {}
        scars = self._raw_scars
        meta = getattr(self, "_episode_meta", {}) or {}
        report: dict = {"n_scars": len(scars), "wisdom_added": [], "intuition_deltas": {}, "cleared_raw": False}

        if not scars and not meta:
            return report

        # --- count scar classes (accept all, do not moralize) ---
        reasons = [str(s.get("reason", "")) for s in scars]
        n_tighten = sum(1 for r in reasons if "tighten" in r or "floor" in r)
        n_climb = sum(1 for r in reasons if "climb" in r or "calm" in r or "loosen" in r)
        final_alive = meta.get("final_alive")
        hard_break = meta.get("first_hard_break")
        soft_break = meta.get("first_soft_break")
        recovery_peak = meta.get("recovery_peak")
        recovery_late = meta.get("recovery_late")

        if not isinstance(self.wisdom, dict) or not self.wisdom:
            self.wisdom = dict(PROMOTED_DNA.get("wisdom_summary", {}))

        # --- compressed rules (wisdom, not diary) ---
        if n_tighten >= 3:
            rule = "under saturated shared quota: cool thrash first; reopen only when budget funds attempts"
            self.wisdom["quota_budget_gate"] = rule
            report["wisdom_added"].append(("quota_budget_gate", rule))
        if hard_break is None and meta.get("survived_long_hell"):
            rule = "long continuous hell can keep fleet alive near target; low success floor is expected until calm"
            self.wisdom["survive_before_goodput"] = rule
            report["wisdom_added"].append(("survive_before_goodput", rule))
        if n_climb >= 1 and recovery_peak is not None and float(recovery_peak) >= 0.55:
            rule = "when env softens, reopen traffic and climb; recovery peaks are real if cool held in hell"
            self.wisdom["recovery_climb"] = rule
            report["wisdom_added"].append(("recovery_climb", rule))
        if soft_break is not None and hard_break is None:
            rule = "soft break = utility floor under thrash; hard break = fleet death — do not confuse them"
            self.wisdom["soft_vs_hard_break"] = rule
            report["wisdom_added"].append(("soft_vs_hard_break", rule))

        # Always reinforce anti-lock (never "learn" to live at 1.0 from trauma)
        self.wisdom["anti_lock"] = "do not live at 1.0; soft ceiling 0.97"
        self.wisdom["paradox_scar_path"] = (
            "raw episode scars absorbed by Paradox only; swarm receives instincts, not terror"
        )

        # --- bright-path counts (success / optimism, not only trauma) ---
        n_bright = sum(
            1
            for r in reasons
            if any(
                k in r
                for k in (
                    "bright",
                    "success",
                    "win",
                    "settle_alive",
                    "mild_ok",
                    "good_day",
                )
            )
        )
        n_climb = n_climb + n_bright  # bright wins count as climb fuel

        # --- tiny intuition nudges (capped) — competence, not fear ---
        deltas = {}
        # Trauma path: only when tighten clearly dominates climb/bright
        if n_tighten > n_climb and n_tighten >= 2:
            deltas["failure_respect"] = min(max_intuition_delta, 0.035 + 0.004 * min(n_tighten, 8))
            deltas["damper_bias"] = min(max_intuition_delta, 0.025 + 0.003 * min(n_tighten, 8))
            # softer explore cut than before (anti-PTSD)
            deltas["explore_bias"] = -min(max_intuition_delta * 0.35, 0.015)
        # Bright / recovery path: generally optimistic competence
        if n_climb >= 2 or n_bright >= 2 or (
            recovery_late is not None and float(recovery_late) >= 0.55
        ):
            deltas["repair_bias"] = max(
                deltas.get("repair_bias", 0.0), min(max_intuition_delta, 0.04)
            )
            deltas["floor_boost"] = max(deltas.get("floor_boost", 0.0), min(0.025, 0.015))
            deltas["pairing_strength"] = max(
                deltas.get("pairing_strength", 0.0), min(max_intuition_delta, 0.03)
            )
            # mild explore floor — willingness to re-enter, not recklessness
            deltas["explore_bias"] = max(deltas.get("explore_bias", 0.0), min(0.02, 0.012))
            # if bright dominates, ease damper slightly (not freeze)
            if n_climb + n_bright > n_tighten + 1:
                deltas["damper_bias"] = min(deltas.get("damper_bias", 0.0), -0.01)
        if hard_break is None and final_alive is not None:
            deltas["pairing_strength"] = max(
                deltas.get("pairing_strength", 0.0), min(max_intuition_delta, 0.025)
            )
            deltas["countermeasure_invest"] = min(max_intuition_delta, 0.03)
        if meta.get("bright_week") or meta.get("optimistic_pass"):
            self.wisdom["bright_path"] = (
                "success and recovery scars build competent optimism; trauma must not monopolize intuition"
            )
            report["wisdom_added"].append(("bright_path", self.wisdom["bright_path"]))
            deltas["repair_bias"] = max(deltas.get("repair_bias", 0.0), 0.03)
            deltas["explore_bias"] = max(deltas.get("explore_bias", 0.0), 0.015)
            deltas["failure_respect"] = min(deltas.get("failure_respect", 0.0), 0.01)

        # soft caps — trauma must not freeze the swarm
        DAMPER_SOFT = 2.30
        for k, d in deltas.items():
            if k == "target_coherence":
                continue
            old = float(self.intuition.get(k, 1.0))
            new = float(np.clip(old + d, 0.05, 2.5))
            if k == "damper_bias":
                new = min(new, DAMPER_SOFT)
            if k == "explore_bias":
                new = float(np.clip(new, 0.06, 0.55))
            self.intuition[k] = new
            report["intuition_deltas"][k] = {"from": old, "to": new, "delta": d}

        # Always reinforce anti-lock + bright balance
        self.wisdom["anti_lock"] = "do not live at 1.0; soft ceiling 0.97"
        self.wisdom.setdefault(
            "bright_path",
            "success and recovery scars build competent optimism; trauma must not monopolize intuition",
        )

        # Clear raw buffer after compression — trauma does not linger as raw tape
        self._raw_scars = []
        report["cleared_raw"] = True
        report["n_bright"] = n_bright
        report["n_climb"] = n_climb
        report["n_tighten"] = n_tighten
        report["episode_meta_kept"] = {
            k: meta.get(k)
            for k in (
                "recovery_peak",
                "recovery_late",
                "first_soft_break",
                "first_hard_break",
                "survived_long_hell",
                "bright_week",
                "optimistic_pass",
            )
            if k in meta
        }
        return report

    def absorb_bright_wins(
        self,
        wins: list,
        *,
        episode_meta: dict | None = None,
    ) -> None:
        """
        Bright-path intake: successful / mild / recovery episodes.
        Same buffer as scars — compress balances them against trauma.
        Tag reasons with bright_/success_/climb_ so compress weights optimism.
        """
        tagged = []
        for w in wins or []:
            w = dict(w)
            r = str(w.get("reason", "bright_win"))
            if not any(k in r for k in ("bright", "success", "climb", "settle", "mild", "win")):
                w["reason"] = f"bright_{r}"
            tagged.append(w)
        meta = dict(episode_meta or {})
        meta.setdefault("optimistic_pass", True)
        self.absorb_episode(tagged, episode_meta=meta)

    def install_drivers(self, agents: list[SwarmMember]):
        """One-way gift of instinct. Swarm does not know the source."""
        base = self.intuition
        for a in agents:
            inst = dict(a.instinct)
            for k in default_instinct():
                if k in base:
                    inst[k] = float(0.65 * inst.get(k, base[k]) + 0.35 * float(base[k]))
            inst["target_coherence"] = float(
                np.clip(base.get("target_coherence", TARGET_STABILITY), 0.7, 0.98)
            )
            a.instinct = inst

    def rank(self, agents: list[SwarmMember]) -> np.ndarray:
        return np.argsort(np.array([a.performance for a in agents]))

    def hive_pair_churn(self, agents: list[SwarmMember], rng: np.random.Generator) -> None:
        """Toroidal hive: bottom5%↔mid5%, then top5%↔new mid5%."""
        n = len(agents)
        k = max(1, int(round(n * PAIR_FRAC)))
        s = float(self.intuition.get("pairing_strength", 0.55))

        def blend(i: int, j: int, elite: bool = False):
            a, b = agents[i], agents[j]
            for key in default_instinct():
                va, vb = a.instinct.get(key, 0.5), b.instinct.get(key, 0.5)
                if elite:
                    a.instinct[key] = float((1 - 0.35 * s) * va + 0.35 * s * vb)
                    b.instinct[key] = float((1 - 0.55 * s) * vb + 0.55 * s * va)
                else:
                    a.instinct[key] = float((1 - 0.65 * s) * va + 0.65 * s * vb)
                    b.instinct[key] = float((1 - 0.25 * s) * vb + 0.25 * s * va)
            if elite:
                b.coherence = float(np.clip(0.7 * b.coherence + 0.3 * a.coherence, 0, 1))
                a.coherence = float(np.clip(0.9 * a.coherence + 0.1 * b.coherence, 0, 1))
            else:
                a.coherence = float(
                    np.clip(
                        0.55 * a.coherence
                        + 0.45 * b.coherence
                        + self.intuition.get("floor_boost", 0.04),
                        0,
                        1,
                    )
                )
                b.coherence = float(np.clip(0.85 * b.coherence + 0.15 * a.coherence, 0, 1))
            a.coherence = min(a.coherence, CEILING_SOFT)
            b.coherence = min(b.coherence, CEILING_SOFT)

        order = self.rank(agents)
        bottom = order[:k]
        mid = order[n // 2 - k // 2 : n // 2 - k // 2 + k]
        for bi, mi in zip(bottom, mid):
            blend(int(bi), int(mi), elite=False)
        order2 = self.rank(agents)
        top = order2[-k:]
        new_mid = order2[n // 2 - k // 2 : n // 2 - k // 2 + k]
        for ti, mi in zip(top, new_mid):
            blend(int(ti), int(mi), elite=True)


# =============================================================================
# RUNTIME
# =============================================================================
def make_swarm(rng: np.random.Generator) -> list[SwarmMember]:
    return [
        SwarmMember(
            id=i,
            coherence=float(rng.uniform(0.45, 0.70)),
            flux=float(rng.normal(0, 0.15)),
            velocity=0.0,
            instinct=default_instinct(),
        )
        for i in range(N_AGENTS)
    ]


def stability(agents: list[SwarmMember]) -> float:
    return float(np.mean([a.coherence for a in agents]))


def run_demo(steps: int = 80, seed: int = 42, I: float | None = None) -> dict:
    """
    Run promoted kernel. learn=False for frozen DNA behavior.
    If I is None, uses mild variable walk in storm-capable band.
    """
    rng = np.random.default_rng(seed)
    agents = make_swarm(rng)
    paradox = Paradox(PROMOTED_DNA)
    paradox.install_drivers(agents)

    series = []
    ambient = 0.0
    i_cur = 1.8 if I is None else float(I)
    for t in range(steps):
        if I is None:
            i_cur = float(np.clip(i_cur + rng.normal(0, 0.08), 0.8, 3.0))
            if rng.random() < 0.08:
                i_cur = float(rng.choice([1.0, 1.5, 2.2, 2.8, 3.0]))  # jump
        for a in agents:
            a.step(i_cur, ambient, rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, rng)
        paradox.install_drivers(agents)  # freeze DNA feel after churn
        for a in agents:
            tcoh = a.instinct.get("target_coherence", TARGET_STABILITY)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tcoh) - 0.4 * a.pred_error, 0, 1)
            )
        series.append({"t": t, "I": i_cur, "stability": stability(agents)})

    arr = np.array([s["stability"] for s in series])
    return {
        "kernel_version": KERNEL_VERSION,
        "kernel_status": KERNEL_STATUS,
        "steps": steps,
        "mean_stability": float(np.mean(arr)),
        "late_stability": float(np.mean(arr[-max(1, steps // 5) :])),
        "min_stability": float(np.min(arr)),
        "max_stability": float(np.max(arr)),
        "locked_frac": float(np.mean(arr >= CEILING_SOFT)),
        "target": TARGET_STABILITY,
        "series": series,
        "final_coherences": [a.coherence for a in agents],
    }


def print_status():
    print("=" * 64)
    print(f"  PARADOX / SWARM KERNEL  v{KERNEL_VERSION}")
    print(f"  Status: {KERNEL_STATUS}")
    print("=" * 64)
    print(f"  Target stability : {TARGET_STABILITY}")
    print(f"  Anti-lock ceiling: {CEILING_SOFT}")
    print(f"  Agents / pair %  : {N_AGENTS} / {PAIR_FRAC*100:.0f}%")
    print(f"  One-way Paradox  : {ONE_WAY_PARADOX}")
    print("  Hive churn       : bottom5%↔mid5% then top5%↔new mid5%")
    print("  Promoted DNA     : embedded (multi-seed exam READY)")
    print("  Wisdom summary   :")
    for k, v in PROMOTED_DNA.get("wisdom_summary", {}).items():
        print(f"    · {k}: {v}")
    print("=" * 64)
    print("  Intuition DNA:")
    for k, v in PROMOTED_DNA["intuition"].items():
        print(f"    {k:24s} {v}")
    print("=" * 64)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Paradox/Swarm Kernel v1.0 — single file")
    p.add_argument("--status", action="store_true", help="Print kernel status and DNA")
    p.add_argument("--demo", type=int, nargs="?", const=80, metavar="STEPS", help="Run demo")
    p.add_argument("--export-dna", type=str, metavar="PATH", help="Write DNA JSON to path")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--I", type=float, default=None, help="Fixed interference (default: variable)")
    args = p.parse_args(argv)

    if args.export_dna:
        paradox = Paradox(PROMOTED_DNA)
        path = args.export_dna
        with open(path, "w", encoding="utf-8") as f:
            json.dump(paradox.export_dna(), f, indent=2)
        print(f"DNA exported → {path}")
        return 0

    if args.status and args.demo is None:
        print_status()
        return 0

    # default: status + demo
    print_status()
    steps = args.demo if args.demo is not None else 80
    print(f"\nRunning demo ({steps} steps, seed={args.seed})…\n")
    result = run_demo(steps=steps, seed=args.seed, I=args.I)
    print(f"  mean stability : {result['mean_stability']:.4f}")
    print(f"  late stability : {result['late_stability']:.4f}")
    print(f"  min / max      : {result['min_stability']:.4f} / {result['max_stability']:.4f}")
    print(f"  locked frac    : {result['locked_frac']:.4f}")
    print(f"  target         : {result['target']}")
    print("\n  Kernel v1.0 ready. Save this file. You did it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
