"""
Beacons-under-latch + bright-path — 3 test rounds
=================================================
Round design (beneficial, not nuke):
  R1  tough week only (storm auto + beacons)
  R2  bright week (successful mild/recover) then tough week  — anti-PTSD diet
  R3  same as R2 with different seeds — stability of gains

Arms:
  A) baseline (no health)
  B) engine storm=off (no auto shell/beacons)
  C) engine storm=auto + beacons (default arsenal)
  D) C + bright-path Paradox pre-feed (success scars before tough)

  python real_world/beacon_bright_compare.py
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K
from nodes.actuate import apply_beacons_to_swarm, apply_shield, plan_actions
from nodes.engine_loop import HealthEngine
from nodes.ingest import to_interference

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = K.TARGET_STABILITY
STEPS_DAY = 24
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# Reuse tough-week + bright-week schedules
def tough_week_schedule(rng):
    env, bud, empty, day, hour = [], [], [], [], []
    for d, name in enumerate(DAYS):
        for h in range(STEPS_DAY):
            if h < 6:
                base_I, base_b = 0.85, 1.0
            elif h < 12:
                base_I, base_b = 1.3, 0.92
            elif h < 18:
                base_I, base_b = 1.4, 0.88
            else:
                base_I, base_b = 1.05, 0.98
            te = 0.04
            if name == "Mon":
                I, b = base_I, base_b
            elif name == "Tue":
                I = base_I + (0.5 if 13 <= h <= 17 else 0.1)
                b = base_b * (0.85 if 13 <= h <= 16 else 1.0)
                te = 0.08 if 13 <= h <= 17 else 0.05
            elif name == "Wed":
                if 10 <= h <= 19:
                    I = 2.15 + 0.2 * np.sin((h - 10) / 3)
                    b = 0.55
                else:
                    I, b = base_I + 0.15, 0.8
                te = 0.06
            elif name == "Thu":
                I = base_I + 0.25
                b = base_b * 0.9
                te = 0.22 + (0.1 if 9 <= h <= 16 else 0)
            elif name == "Fri":
                I = base_I + 0.35 + (0.35 if 11 <= h <= 16 else 0)
                b = float(np.clip(0.42 + 0.02 * max(0, h - 14), 0.4, 0.75))
                te = 0.1
            elif name == "Sat":
                I, b, te = 0.95, 0.9, 0.05
            else:
                if h < 14:
                    I, b, te = 1.5, 0.75, 0.07
                else:
                    I, b, te = 1.05, 1.0, 0.04
            env.append(float(np.clip(I + rng.normal(0, 0.04), 0.5, 2.55)))
            bud.append(float(np.clip(b, 0.35, 1.1)))
            empty.append(float(np.clip(te, 0, 0.5)))
            day.append(name)
            hour.append(h)
    return env, bud, empty, day, hour


def bright_week_schedule(rng):
    """Successful milder week — wins for bright-path scars."""
    env, bud, empty, day, hour = [], [], [], [], []
    for d, name in enumerate(DAYS):
        for h in range(STEPS_DAY):
            # mostly calm productive load
            I = 1.05 + 0.15 * (1 if 9 <= h <= 17 else 0) + rng.normal(0, 0.03)
            b = 0.95
            te = 0.03
            if name == "Wed" and 12 <= h <= 15:
                I = 1.55  # mild blip, not hell
                b = 0.85
            env.append(float(np.clip(I, 0.6, 1.7)))
            bud.append(b)
            empty.append(te)
            day.append(name)
            hour.append(h)
    return env, bud, empty, day, hour


class World:
    def __init__(self, n=28, budget=13.0, rng=None):
        self.n = n
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n, dtype=bool)
        self.fail = np.zeros(n, dtype=int)
        self.recent_ok = []
        self.recent_gp = []
        self.recent_empty = []
        self.retries = 0.0
        self.budget_mul = 1.0
        self.tool_empty = 0.0

    def rs(self):
        return 0.6 if not self.recent_ok else float(np.mean(self.recent_ok[-60:]))

    def rgp(self):
        return 0.35 if not self.recent_gp else float(np.mean(self.recent_gp[-20:]))

    def rempty(self):
        return 0.0 if not self.recent_empty else float(np.mean(self.recent_empty[-40:]))

    def step(self, env_I):
        capacity = self.base_budget * float(np.clip(self.budget_mul, 0.05, 1.2)) * max(
            0.12, 1.0 - 0.26 * env_I
        )
        active = list(np.where(self.alive)[0])
        demand = len(active) + int(round(self.retries * len(active)))
        if demand <= 0:
            self.recent_gp.append(0.0)
            return {"gp": self.rgp(), "alive": 0, "retries": self.retries, "empty": self.rempty(), "sr": self.rs()}
        serve = int(min(demand, max(0, round(capacity))))
        flake = float(np.clip(0.05 + 0.12 * env_I, 0.04, 0.55))
        empty_p = float(np.clip(self.tool_empty, 0, 0.75))
        ok = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            if i < serve and self.rng.random() > flake:
                if self.rng.random() < empty_p:
                    self.fail[c] += 1
                    self.recent_ok.append(0)
                    self.recent_empty.append(1.0)
                    self.retries = min(2.8, self.retries + 0.03)
                else:
                    ok += 1
                    self.fail[c] = max(0, self.fail[c] - 1)
                    self.recent_ok.append(1)
                    self.recent_empty.append(0.0)
            else:
                self.fail[c] += 1
                self.recent_ok.append(0)
                self.recent_empty.append(0.0)
                self.retries = min(2.8, self.retries + 0.035)
                if self.fail[c] >= 7 and self.rng.random() < 0.28:
                    self.alive[c] = False
        if ok == demand:
            self.retries = max(0.0, self.retries - 0.07)
        gp = ok / self.n
        self.recent_gp.append(gp)
        if len(self.recent_ok) > 300:
            self.recent_ok = self.recent_ok[-300:]
        if len(self.recent_gp) > 80:
            self.recent_gp = self.recent_gp[-80:]
        return {
            "gp": self.rgp(),
            "alive": int(np.sum(self.alive)),
            "retries": self.retries,
            "empty": self.rempty(),
            "sr": self.rs(),
            "br": float(np.clip(self.budget_mul, 0, 1)),
        }

    def quarantine(self, k):
        idx = np.where(self.alive)[0]
        for i in sorted(idx, key=lambda j: -self.fail[j])[:k]:
            self.alive[i] = False

    def revive(self, k):
        for i in np.where(~self.alive)[0][:k]:
            self.alive[i] = True
            self.fail[i] = 0


def apply_plan(w: World, plan):
    if plan.cool_retries:
        w.retries = max(0.0, w.retries * (0.66 if plan.storm_active else 0.75))
    if plan.quarantine_k:
        w.quarantine(plan.quarantine_k)
    if plan.revive_k:
        w.revive(plan.revive_k if plan.open_traffic or not plan.storm_active else min(1, plan.revive_k))


def feed_bright(paradox: K.Paradox, seed: int):
    """Successful mild week → bright scars into Paradox (anti-PTSD diet)."""
    rng = np.random.default_rng(seed)
    env, bud, empty, days, _ = bright_week_schedule(rng)
    w = World(rng=np.random.default_rng(seed + 1))
    eng = HealthEngine(seed=seed + 2, storm_mode="auto")
    # share paradox into eng
    eng.paradox = paradox
    eng.paradox.install_drivers(eng.agents)
    wins = []
    gps = []
    for t in range(len(env)):
        w.budget_mul = bud[t]
        w.tool_empty = empty[t]
        out = eng.step_from_metrics(
            success_rate=w.rs(),
            env_load=env[t],
            thrash=w.retries,
            goodput=w.rgp(),
            budget_remaining=bud[t],
            empty_tool_rate=w.rempty(),
        )
        felt = apply_shield(env[t], out["plan"])
        m = w.step(felt)
        apply_plan(w, out["plan"])
        gps.append(m["gp"])
        if m["gp"] >= 0.35 and m["alive"] >= 20:
            wins.append({"reason": "bright_mild_ok", "gp": m["gp"], "day": days[t]})
        if m["gp"] >= 0.40:
            wins.append({"reason": "bright_success", "gp": m["gp"]})
        if days[t] == "Sun" and m["alive"] >= 22:
            wins.append({"reason": "settle_alive", "alive": m["alive"]})
    paradox.absorb_bright_wins(
        wins,
        episode_meta={
            "bright_week": True,
            "optimistic_pass": True,
            "recovery_late": float(np.mean(gps[-24:])),
            "recovery_peak": float(np.max(gps)),
            "final_alive": True,
        },
    )
    return paradox.compress_scars_to_wisdom(max_intuition_delta=0.07)


def run_tough(name, seed, storm_mode, paradox=None):
    rng = np.random.default_rng(seed)
    env, bud, empty, days, hours = tough_week_schedule(rng)
    w = World(rng=np.random.default_rng(seed + 3))

    if name == "baseline":
        rows = []
        for t in range(len(env)):
            w.budget_mul = bud[t]
            w.tool_empty = empty[t]
            m = w.step(env[t])
            if m["gp"] < 0.25:
                w.retries = min(2.8, w.retries + 0.02)
            rows.append({**m, "day": days[t], "storm": False, "beacon": False, "stab": None})
        return summarize(name, rows)

    eng = HealthEngine(seed=seed + 9, storm_mode=storm_mode)
    if paradox is not None:
        eng.paradox = paradox
        eng.paradox.install_drivers(eng.agents)

    rows = []
    beacon_steps = 0
    for t in range(len(env)):
        w.budget_mul = bud[t]
        w.tool_empty = empty[t]
        out = eng.step_from_metrics(
            success_rate=w.rs(),
            env_load=env[t],
            thrash=w.retries + w.rempty(),
            goodput=w.rgp(),
            budget_remaining=bud[t],
            empty_tool_rate=w.rempty(),
        )
        plan = out["plan"]
        felt = apply_shield(env[t], plan)
        m = w.step(felt)
        apply_plan(w, plan)
        if plan.beacon_active:
            beacon_steps += 1
        rows.append(
            {
                **m,
                "day": days[t],
                "storm": plan.storm_active,
                "beacon": plan.beacon_active,
                "stab": out["stability"],
                "pulled": out.get("beacon_pulled", 0),
            }
        )
    s = summarize(name, rows)
    s["beacon_frac"] = beacon_steps / max(1, len(rows))
    s["storm_frac"] = float(np.mean([1.0 if r["storm"] else 0.0 for r in rows]))
    if paradox is not None:
        s["intuition"] = {
            k: float(paradox.intuition.get(k, 0))
            for k in (
                "damper_bias",
                "repair_bias",
                "explore_bias",
                "failure_respect",
                "pairing_strength",
                "countermeasure_invest",
            )
        }
    return s


def summarize(name, rows):
    gp = np.array([r["gp"] for r in rows])
    alive = np.array([r["alive"] for r in rows], float)
    by_day = {}
    for d in DAYS:
        idx = [i for i, r in enumerate(rows) if r["day"] == d]
        by_day[d] = {
            "gp": float(np.mean(gp[idx])),
            "alive": float(np.mean(alive[idx])),
        }
    return {
        "name": name,
        "gp_mean": float(np.mean(gp)),
        "gp_sun": float(np.mean(gp[-STEPS_DAY:])),
        "alive_end": float(alive[-1]),
        "alive_mean": float(np.mean(alive)),
        "alive_min": float(np.min(alive)),
        "by_day": by_day,
        "beacon_frac": 0.0,
        "storm_frac": 0.0,
    }


def main():
    print("=" * 70)
    print(" BEACONS + BRIGHT-PATH — 3 test rounds")
    print("=" * 70)

    all_rounds = []
    seeds_rounds = [
        [7, 11, 21],
        [13, 29, 37],
        [42, 53, 71],
    ]

    for ri, seeds in enumerate(seeds_rounds, 1):
        print(f"\n### ROUND {ri} seeds={seeds}")
        pack = {"round": ri, "arms": {}}
        for arm in ("baseline", "engine_off", "storm_beacons", "bright_then_storm"):
            runs = []
            for seed in seeds:
                if arm == "baseline":
                    runs.append(run_tough("baseline", seed, "off"))
                elif arm == "engine_off":
                    runs.append(run_tough("engine_off", seed, "off"))
                elif arm == "storm_beacons":
                    runs.append(run_tough("storm_beacons", seed, "auto"))
                else:
                    px = K.Paradox(copy.deepcopy(K.PROMOTED_DNA))
                    rep = feed_bright(px, seed + 100)
                    r = run_tough("bright_then_storm", seed, "auto", paradox=px)
                    r["bright_report"] = {
                        "n_bright": rep.get("n_bright"),
                        "n_climb": rep.get("n_climb"),
                        "deltas": rep.get("intuition_deltas"),
                    }
                    runs.append(r)

            def mean_key(k):
                return float(np.mean([x[k] for x in runs if k in x and x[k] is not None]))

            pack["arms"][arm] = {
                "gp_mean": mean_key("gp_mean"),
                "gp_sun": mean_key("gp_sun"),
                "alive_end": mean_key("alive_end"),
                "alive_mean": mean_key("alive_mean"),
                "storm_frac": mean_key("storm_frac"),
                "beacon_frac": mean_key("beacon_frac"),
                "by_day_gp": {
                    d: float(np.mean([x["by_day"][d]["gp"] for x in runs])) for d in DAYS
                },
            }
            a = pack["arms"][arm]
            print(
                f"  {arm:18s}  gp={a['gp_mean']:.3f}  sun={a['gp_sun']:.3f}  "
                f"alive_end={a['alive_end']:.1f}  storm%={100*a['storm_frac']:.0f}  "
                f"beacon%={100*a['beacon_frac']:.0f}"
            )
        all_rounds.append(pack)

    # Aggregate across 3 rounds
    print("\n" + "=" * 70)
    print(" CROSS-ROUND MEAN")
    print("=" * 70)
    arms = list(all_rounds[0]["arms"].keys())
    agg = {}
    for arm in arms:
        agg[arm] = {
            k: float(np.mean([r["arms"][arm][k] for r in all_rounds]))
            for k in ("gp_mean", "gp_sun", "alive_end", "alive_mean", "storm_frac", "beacon_frac")
        }
        print(
            f"  {arm:18s}  gp={agg[arm]['gp_mean']:.3f}  sun={agg[arm]['gp_sun']:.3f}  "
            f"alive_end={agg[arm]['alive_end']:.1f}  beacon%={100*agg[arm]['beacon_frac']:.0f}"
        )

    print("\n[DELTAS vs baseline]")
    base = agg["baseline"]
    for arm in arms:
        if arm == "baseline":
            continue
        print(
            f"  {arm:18s}  Δgp={agg[arm]['gp_mean']-base['gp_mean']:+.3f}  "
            f"Δalive_end={agg[arm]['alive_end']-base['alive_end']:+.1f}"
        )

    print("\n[STORM+BEACONS vs ENGINE_OFF]")
    sb, eo = agg["storm_beacons"], agg["engine_off"]
    print(f"  Δgp={sb['gp_mean']-eo['gp_mean']:+.3f}  Δalive={sb['alive_end']-eo['alive_end']:+.1f}")

    print("\n[BRIGHT+STORM vs STORM only]")
    br = agg["bright_then_storm"]
    print(
        f"  Δgp={br['gp_mean']-sb['gp_mean']:+.3f}  Δalive={br['alive_end']-sb['alive_end']:+.1f}  "
        f"Δsun={br['gp_sun']-sb['gp_sun']:+.3f}"
    )

    # suggestions
    suggestions = []
    if sb["gp_mean"] > eo["gp_mean"] + 0.005 or sb["alive_end"] > eo["alive_end"] + 0.5:
        suggestions.append("Keep beacons under storm latch — measurable lift vs engine_off.")
    else:
        suggestions.append("Beacons flat on week metrics — tune pull or edge_frac; shell may dominate.")
    if br["gp_mean"] >= sb["gp_mean"] - 0.005 and br["alive_end"] >= sb["alive_end"] - 0.5:
        suggestions.append(
            "Bright-path pre-feed does not hurt tough week; use as anti-PTSD diet between hard sims."
        )
    if br["alive_end"] > sb["alive_end"] + 0.3 or br["gp_sun"] > sb["gp_sun"] + 0.01:
        suggestions.append("Bright pre-feed improves recovery — schedule mild wins before hard weeks in training.")
    else:
        suggestions.append(
            "Bright pre-feed subtle — increase bright scar weight or longer mild weeks before promote exams."
        )
    suggestions.append("Never train only on hell: alternate bright_week : tough_week ~ 1:1 or 2:1.")
    suggestions.append("Outer systems: when plan.beacon_active, prefer healthy workers / drain tail clients.")
    suggestions.append("Do not lower blackout floor yet; tough week + beacons is the product regime.")

    print("\n[SUGGESTIONS]")
    for i, s in enumerate(suggestions, 1):
        print(f"  {i}. {s}")

    # plot
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    labels = ["baseline", "engine_off", "storm+beac", "bright→storm"]
    keys = ["baseline", "engine_off", "storm_beacons", "bright_then_storm"]
    gp = [agg[k]["gp_mean"] for k in keys]
    al = [agg[k]["alive_end"] for k in keys]
    axes[0].bar(labels, gp, color=["#ff6b8a", "#5dffb0", "#40d0ff", "#2ecc71"])
    axes[0].set_ylabel("week goodput")
    axes[0].set_title("3-round mean goodput")
    axes[0].tick_params(axis="x", rotation=15)
    axes[0].grid(True, alpha=0.25, axis="y")
    axes[1].bar(labels, al, color=["#ff6b8a", "#5dffb0", "#40d0ff", "#2ecc71"])
    axes[1].set_ylabel("end alive")
    axes[1].set_title("3-round mean end alive")
    axes[1].tick_params(axis="x", rotation=15)
    axes[1].grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    png = OUT / "beacon_bright_compare.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "proto": "beacon_bright_compare_v1",
        "rounds": all_rounds,
        "aggregate": agg,
        "deltas": {
            "storm_beacons_vs_engine_off_gp": sb["gp_mean"] - eo["gp_mean"],
            "storm_beacons_vs_engine_off_alive": sb["alive_end"] - eo["alive_end"],
            "bright_vs_storm_gp": br["gp_mean"] - sb["gp_mean"],
            "bright_vs_storm_alive": br["alive_end"] - sb["alive_end"],
            "bright_vs_storm_sun": br["gp_sun"] - sb["gp_sun"],
        },
        "suggestions": suggestions,
        "how_optimism_works": {
            "now": (
                "Paradox absorb_bright_wins + compress balances climb/bright scars vs tighten; "
                "raises repair/pairing/explore floor; soft-caps damper; trauma cannot monopolize"
            ),
            "optimal": (
                "Alternate bright weeks and tough weeks; always compress mixed buffers; "
                "promote DNA only after multi-seed exam that includes both; "
                "swarm stays competent-optimistic not frozen or reckless"
            ),
        },
    }
    js = OUT / "beacon_bright_compare_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
