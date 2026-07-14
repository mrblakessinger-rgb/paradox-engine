"""
Paradox credit loop — forecast → actual → counterfactual → intuition
====================================================================
Closed-loop learning Paradox *must* own:

  1) FORECAST  from intuition + wisdom tags + sensors (not swarm-only pred)
  2) RECORD    plan + sensors + forecast each cycle
  3) ACTUAL    after step: stability / goodput / alive
  4) ERROR     |actual - forecast|
  5) COUNTERFACTUAL skim: cheap "what if" alternate plans
  6) BEST PRACTICE for that cycle → capped intuition + wisdom rules

Keeps KERNEL swarm physics clean — this is Paradox control learning.

  from nodes.paradox_credit import CreditEngine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Soft bounds (anti-PTSD / anti-lock)
DAMPER_SOFT = 2.28
REPAIR_SOFT = 2.40
EXPLORE_LO, EXPLORE_HI = 0.06, 0.50
MAX_DELTA_PER_EPISODE = 0.07


@dataclass
class CycleRecord:
    t: int
    env_load: float
    thrash: float
    budget: float
    empty_rate: float
    # forecast
    pred_stab: float
    pred_goodput: float
    # plan snapshot
    storm: bool
    cool: bool
    quarantine_k: int
    revive_k: int
    open_traffic: bool
    beacon: bool
    damper_live: float
    # actual (filled after)
    actual_stab: float = 0.0
    actual_goodput: float = 0.0
    actual_alive_frac: float = 0.0
    # credit
    err_stab: float = 0.0
    err_gp: float = 0.0
    best_action: str = ""
    best_score: float = 0.0
    actual_score: float = 0.0


@dataclass
class CreditEngine:
    """
    Attached to a Paradox instance (or holds intuition dict reference).
    Optimized training: more weight on recoverable regimes; calm-down on blackout.
    """

    intuition: dict
    wisdom: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    episode_errors: list = field(default_factory=list)
    episode_best: list = field(default_factory=list)
    # learning rates (curriculum can scale these)
    lr_scale: float = 1.0
    # rolling calibration
    bias_stab: float = 0.0
    bias_gp: float = 0.0

    def attach_paradox(self, paradox) -> None:
        self.intuition = paradox.intuition
        if not isinstance(paradox.wisdom, dict):
            paradox.wisdom = {}
        self.wisdom = paradox.wisdom
        self.wisdom.setdefault(
            "credit_loop",
            "forecast vs actual + counterfactual best practice feed intuition (capped)",
        )

    # ------------------------------------------------------------------ forecast
    def forecast(
        self,
        *,
        stability: float,
        env_load: float,
        thrash: float = 0.0,
        budget: float = 1.0,
        empty_rate: float = 0.0,
        goodput: float | None = None,
        storm: bool = False,
        damper_live: float | None = None,
    ) -> tuple[float, float]:
        """
        Paradox forecast of next-step stability & goodput from intuition + sensors.
        Not swarm predict_next — higher-level control forecast.
        """
        I = self.intuition
        stab = float(stability)
        env = float(env_load)
        thr = float(max(0.0, thrash))
        br = float(np.clip(budget, 0.0, 1.0))
        empty = float(np.clip(empty_rate, 0.0, 1.0))
        gp0 = float(goodput) if goodput is not None else max(0.15, stab - 0.4)
        damp = float(damper_live if damper_live is not None else I.get("damper_bias", 1.5))

        # stress load
        stress = 0.35 * env + 0.40 * thr + 0.25 * (1.0 - br) + 0.30 * empty
        armor = 0.40 * float(I.get("viscosity_bias", 1.0)) + 0.40 * damp + 0.20 * float(
            I.get("repair_bias", 1.0)
        )
        armor = max(0.8, armor)
        threat = stress / armor

        # stability forecast
        pull = 0.08 * float(I.get("repair_bias", 1.0)) * (
            float(I.get("target_coherence", 0.92)) - stab
        )
        storm_help = 0.04 if storm else 0.0
        pred_stab = stab - 0.10 * threat + pull + storm_help + self.bias_stab
        pred_stab = float(np.clip(pred_stab, 0.0, 0.97))

        # goodput forecast (control-level)
        base_gp = gp0 * (0.55 + 0.45 * br)
        pred_gp = base_gp * (1.0 - 0.22 * min(2.0, threat)) * (1.0 - 0.35 * empty)
        if storm:
            pred_gp *= 1.08  # expect shell to help a bit
        if thr > 1.0 and not storm:
            pred_gp *= 0.85  # expect stampede pain
        pred_gp = float(np.clip(pred_gp + self.bias_gp, 0.0, 1.0))
        return pred_stab, pred_gp

    def open_cycle(
        self,
        t: int,
        *,
        env_load: float,
        thrash: float,
        budget: float,
        empty_rate: float,
        stability: float,
        goodput: float | None,
        plan: Any,
        damper_live: float,
    ) -> CycleRecord:
        storm = bool(getattr(plan, "storm_active", False))
        pred_s, pred_g = self.forecast(
            stability=stability,
            env_load=env_load,
            thrash=thrash,
            budget=budget,
            empty_rate=empty_rate,
            goodput=goodput,
            storm=storm,
            damper_live=damper_live,
        )
        rec = CycleRecord(
            t=t,
            env_load=float(env_load),
            thrash=float(thrash),
            budget=float(budget),
            empty_rate=float(empty_rate),
            pred_stab=pred_s,
            pred_goodput=pred_g,
            storm=storm,
            cool=bool(getattr(plan, "cool_retries", False)),
            quarantine_k=int(getattr(plan, "quarantine_k", 0)),
            revive_k=int(getattr(plan, "revive_k", 0)),
            open_traffic=bool(getattr(plan, "open_traffic", False)),
            beacon=bool(getattr(plan, "beacon_active", False)),
            damper_live=float(damper_live),
        )
        self.log.append(rec)
        return rec

    def close_cycle(
        self,
        *,
        actual_stab: float,
        actual_goodput: float,
        actual_alive_frac: float,
    ) -> CycleRecord | None:
        if not self.log:
            return None
        rec = self.log[-1]
        rec.actual_stab = float(actual_stab)
        rec.actual_goodput = float(actual_goodput)
        rec.actual_alive_frac = float(actual_alive_frac)
        rec.err_stab = abs(rec.actual_stab - rec.pred_stab)
        rec.err_gp = abs(rec.actual_goodput - rec.pred_goodput)
        # score: goodput + alive + stability (control objective)
        rec.actual_score = self._score(
            rec.actual_goodput, rec.actual_alive_frac, rec.actual_stab, rec.env_load, rec.thrash
        )
        best_name, best_sc = self._counterfactual(rec)
        rec.best_action = best_name
        rec.best_score = best_sc
        self.episode_errors.append((rec.err_stab, rec.err_gp))
        self.episode_best.append((best_name, best_sc - rec.actual_score))
        return rec

    def _score(self, gp: float, alive: float, stab: float, env: float, thr: float) -> float:
        # Emphasize survival under stress; goodput when env allows
        stress = min(1.0, 0.4 * env + 0.4 * thr)
        return float(
            0.40 * gp + 0.35 * alive + 0.25 * stab - 0.05 * stress * (1.0 - alive)
        )

    def _counterfactual(self, rec: CycleRecord) -> tuple[str, float]:
        """
        Cheap counterfactual skim — estimate score under alternate control postures.
        Not full resim; heuristic from sensors + what we know about arsenal.
        """
        env, thr, br, empty = rec.env_load, rec.thrash, rec.budget, rec.empty_rate
        gp, alive, stab = rec.actual_goodput, rec.actual_alive_frac, rec.actual_stab

        candidates: dict[str, float] = {"actual": rec.actual_score}

        # what if storm armed (shell+beacon) — survival-leaning, modest gp
        if not rec.storm and (thr > 0.55 or br < 0.55 or env >= 1.7):
            gp_s = min(1.0, gp * 1.06 + 0.01)
            alive_s = min(1.0, alive + 0.10 * min(1.0, thr + (1.0 - br)))
            stab_s = min(0.97, stab + 0.015)
            if env > 2.6 and br < 0.25:
                gp_s = gp * 1.01
            candidates["arm_storm_earlier"] = self._score(gp_s, alive_s, stab_s, env, thr)

        # what if cooler thrash harder — only when thrash is severe (avoid over-cool bias)
        if thr > 0.95:
            gp_c = min(1.0, gp * 1.04)
            alive_c = min(1.0, alive + 0.03)
            candidates["cool_harder"] = self._score(gp_c, alive_c, stab + 0.01, env, thr * 0.75)

        # what if more revive in recover-ish (widened — primary survival CF)
        if alive < 0.75 and env < 2.3:
            alive_r = min(1.0, alive + 0.12)
            gp_r = min(1.0, gp * 1.05 + 0.015)
            candidates["revive_more"] = self._score(gp_r, alive_r, stab, env, thr)

        # what if open traffic (only if calm enough)
        if env < 1.5 and thr < 0.45 and br > 0.6:
            gp_o = min(1.0, gp * 1.08)
            candidates["open_traffic"] = self._score(gp_o, alive, stab, env, thr)

        # what if fail-closed on empty tools
        if empty > 0.12:
            gp_e = min(1.0, gp * (1.0 + 0.15 * empty))
            candidates["fail_closed_tools"] = self._score(gp_e, alive, stab, env, thr)

        # what if hold / less cool (sometimes over-cool)
        if rec.cool and thr < 0.4 and env < 1.6:
            gp_h = min(1.0, gp * 1.05)
            candidates["less_cool"] = self._score(gp_h, alive, stab, env, thr)

        # damper higher under thrash
        if thr > 0.7 and rec.damper_live < 2.15:
            candidates["damper_up"] = self._score(
                min(1.0, gp * 1.03), min(1.0, alive + 0.03), min(0.97, stab + 0.015), env, thr
            )

        best = max(candidates.items(), key=lambda kv: kv[1])
        return best[0], float(best[1])

    def end_episode_learn(self, *, max_delta: float | None = None) -> dict:
        """
        After an episode: calibrate forecast bias + apply best-practice deltas.
        Optimized: only learn when counterfactual margin is clear; mix bright/tough.
        """
        md = MAX_DELTA_PER_EPISODE if max_delta is None else float(max_delta)
        md *= float(self.lr_scale)
        report: dict[str, Any] = {
            "n_cycles": len(self.log),
            "mean_err_stab": 0.0,
            "mean_err_gp": 0.0,
            "best_action_counts": {},
            "intuition_deltas": {},
            "wisdom_added": [],
            "calibrated": False,
        }
        if not self.log:
            return report

        closed = [r for r in self.log if r.actual_score > 0 or r.err_stab > 0 or r.t >= 0]
        # use all with filled actuals
        closed = [r for r in self.log if r.err_stab > 0 or r.actual_goodput > 0 or r.actual_stab > 0]
        if not closed:
            closed = list(self.log)

        report["mean_err_stab"] = float(np.mean([r.err_stab for r in closed]))
        report["mean_err_gp"] = float(np.mean([r.err_gp for r in closed]))

        # --- calibrate forecast biases (slow) ---
        mean_ds = float(np.mean([r.actual_stab - r.pred_stab for r in closed]))
        mean_dg = float(np.mean([r.actual_goodput - r.pred_goodput for r in closed]))
        self.bias_stab = float(np.clip(self.bias_stab + 0.15 * mean_ds, -0.08, 0.08))
        self.bias_gp = float(np.clip(self.bias_gp + 0.15 * mean_dg, -0.08, 0.08))
        report["calibrated"] = True
        report["bias_stab"] = self.bias_stab
        report["bias_gp"] = self.bias_gp

        # --- count best practices that beat actual by margin ---
        counts: dict[str, int] = {}
        regret_sum: dict[str, float] = {}
        for r in closed:
            if r.best_action and r.best_action != "actual" and (r.best_score - r.actual_score) > 0.01:
                counts[r.best_action] = counts.get(r.best_action, 0) + 1
                regret_sum[r.best_action] = regret_sum.get(r.best_action, 0.0) + (
                    r.best_score - r.actual_score
                )
        report["best_action_counts"] = counts

        # --- map best practices → intuition deltas ---
        deltas: dict[str, float] = {}

        def add(k: str, v: float):
            deltas[k] = deltas.get(k, 0.0) + v

        n = max(1, len(closed))
        # forecast skill: high error → slight predict_trust / failure_respect
        if report["mean_err_stab"] > 0.06 or report["mean_err_gp"] > 0.08:
            add("failure_respect", min(md, 0.02 * self.lr_scale))
            add("predict_trust", min(md * 0.5, 0.015))

        # Only learn from actions that win often enough (avoid noisy CF)
        min_frac = 0.12
        for action, c in counts.items():
            if c / n < min_frac:
                continue
            w = (c / n) * self.lr_scale
            # Prefer survival-positive lessons; soft-pedal pure cool/damper (over-cool kills revive)
            if action == "arm_storm_earlier":
                add("countermeasure_invest", min(md, 0.04 * w * 2.5))
                # small damper only — shell does the heavy lifting
                add("damper_bias", min(md * 0.5, 0.015 * w * 2))
                # Look harder at leading indicators next time (horizon scout)
                add("horizon_sensitivity", min(md, 0.05 * w * 2.2))
                self.wisdom["credit_storm_early"] = (
                    "when thrash/budget stress rises, arm storm pack earlier than reactive default; "
                    "raise horizon sensitivity to pre-arm on leading signs"
                )
                report["wisdom_added"].append("credit_storm_early")
            elif action == "cool_harder":
                # weak: over-cool caused alive regression in exams
                add("failure_respect", min(md * 0.5, 0.012 * w * 2))
                add("damper_bias", min(md * 0.35, 0.01 * w))
                self.wisdom["credit_cool"] = "under retry stampede, cool thrash — but do not freeze revive"
                report["wisdom_added"].append("credit_cool")
            elif action == "revive_more":
                add("repair_bias", min(md, 0.05 * w * 2.5))
                add("pairing_strength", min(md, 0.04 * w * 2.5))
                add("floor_boost", min(0.025, 0.015 * w * 2.5))
                add("damper_bias", -min(0.02, 0.012 * w * 2))  # allow re-entry
                # Internal desire to climb after hurt — grows when revive wins CF
                add("recovery_drive", min(md, 0.045 * w * 2.2))
                self.wisdom["credit_revive"] = "in recover bands, revive more aggressively when budget allows"
                report["wisdom_added"].append("credit_revive")
            elif action == "open_traffic":
                add("explore_bias", min(0.03, 0.025 * w * 2))
                add("repair_bias", min(md, 0.025 * w * 2))
                add("damper_bias", -min(0.025, 0.02 * w * 2))
                add("recovery_drive", min(md, 0.035 * w * 2.0))
                self.wisdom["credit_open"] = "when calm+budget, reopen traffic; do not stay locked cool"
                report["wisdom_added"].append("credit_open")
            elif action == "fail_closed_tools":
                add("failure_respect", min(md, 0.03 * w * 2))
                add("predict_trust", min(md, 0.02 * w))
                self.wisdom["credit_fail_closed"] = (
                    "empty/error tool paths must fail closed — do not invent success"
                )
                report["wisdom_added"].append("credit_fail_closed")
            elif action == "less_cool":
                add("damper_bias", -min(0.03, 0.025 * w * 2))
                add("explore_bias", min(0.025, 0.02 * w * 2))
                add("repair_bias", min(md, 0.02 * w))
                self.wisdom["credit_less_cool"] = "avoid over-cool in mild regimes; protect goodput"
                report["wisdom_added"].append("credit_less_cool")
            elif action == "damper_up":
                add("damper_bias", min(md * 0.5, 0.015 * w * 2))

        # survival priority: if revive regret large, boost repair path
        if regret_sum.get("revive_more", 0) > 0.10:
            add("repair_bias", min(md, 0.03))
            add("pairing_strength", min(md, 0.025))
            add("recovery_drive", min(md, 0.04))
        if regret_sum.get("arm_storm_earlier", 0) > 0.20:
            add("countermeasure_invest", min(md, 0.025))
            add("horizon_sensitivity", min(md, 0.04))
            self.wisdom["horizon_scout"] = (
                "look upstream for surge signs and pre-arm before peak; "
                "credit raises sensitivity when late arming costs survival"
            )
            report["wisdom_added"].append("horizon_sensitivity↑")
        # When open/revive both win often → internal desire to recover hardens
        if counts.get("revive_more", 0) + counts.get("open_traffic", 0) >= max(3, int(0.18 * n)):
            add("recovery_drive", min(md, 0.03))
            self.wisdom["recovery_drive"] = (
                "after storm/load drop, desire to climb: revive harder, open traffic, ease damper"
            )
            report["wisdom_added"].append("recovery_drive_desire")

        # apply with soft caps
        for k, d in deltas.items():
            if k == "target_coherence":
                continue
            old = float(self.intuition.get(k, 1.0 if k != "recovery_drive" else 1.15))
            new = float(np.clip(old + d, 0.05, 2.5))
            if k == "damper_bias":
                new = min(new, DAMPER_SOFT)
                new = max(new, 1.2)
            if k == "repair_bias":
                new = min(new, REPAIR_SOFT)
            if k == "explore_bias":
                new = float(np.clip(new, EXPLORE_LO, EXPLORE_HI))
            if k == "predict_trust":
                new = float(np.clip(new, 0.2, 0.95))
            if k == "recovery_drive":
                # Cap desire so open/revive climb stays surge-resilient, not thrash-runaway
                new = float(np.clip(new, 0.8, 1.90))
            if k == "horizon_sensitivity":
                new = float(np.clip(new, 0.6, 1.7))
            self.intuition[k] = new
            report["intuition_deltas"][k] = {"from": old, "to": new, "delta": d}

        self.wisdom["credit_loop"] = (
            "forecast vs actual + counterfactual best practice feed intuition (capped)"
        )
        # clear cycle log for next episode (keep biases)
        self.log = []
        return report

    def episode_error_summary(self) -> dict:
        if not self.episode_errors:
            return {"n": 0}
        es = np.array(self.episode_errors[-50:], float)
        return {
            "n": int(es.shape[0]),
            "mean_err_stab": float(np.mean(es[:, 0])),
            "mean_err_gp": float(np.mean(es[:, 1])),
            "late_err_stab": float(np.mean(es[-5:, 0])) if len(es) >= 5 else float(np.mean(es[:, 0])),
            "late_err_gp": float(np.mean(es[-5:, 1])) if len(es) >= 5 else float(np.mean(es[:, 1])),
        }
