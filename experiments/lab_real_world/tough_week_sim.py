"""
Tough week — real-world-ish fleet conditions (not a nuke)
========================================================
One simulated work week of multi-client API / tool traffic:

  Mon  steady production
  Tue  deploy + retry thrash (afternoon spike)
  Wed  provider 429 / rate-limit storm
  Thu  flaky tools / empty responses (partial correctness pain)
  Fri  shared quota pinch + backlog
  Sat  quieter + residual retries
  Sun  catch-up traffic, then settle

Arms:
  A) baseline — no health layer
  B) engine storm_mode=off
  C) engine storm_mode=auto

Power stays ~1.0 (no blackout). Stress is load, 429, flake, thrash, budget.
DNA: PROMOTED frozen.

  python real_world/tough_week_sim.py
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
from nodes.actuate import apply_shield, plan_actions
from nodes.ingest import from_api, to_interference

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = K.TARGET_STABILITY
# ~24 steps/day × 7 = 168
STEPS_PER_DAY = 24
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class WeekWorld:
    """
    Shared-budget clients + optional tool-empty rate.
    env_I: demand/storm
    budget_mul: quota availability 0..1
    tool_empty: chance a "success path" is empty/error (still burns call)
    """

    def __init__(self, n=28, budget=13.0, rng=None):
        self.n = n
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n, dtype=bool)
        self.fail = np.zeros(n, dtype=int)
        self.recent_ok: list[int] = []
        self.recent_goodput: list[float] = []
        self.recent_empty: list[float] = []
        self.retries = 0.0
        self.budget_mul = 1.0
        self.tool_empty = 0.0  # 0..1

    def rolling_success(self) -> float:
        return 0.6 if not self.recent_ok else float(np.mean(self.recent_ok[-60:]))

    def rolling_goodput(self) -> float:
        return 0.35 if not self.recent_goodput else float(np.mean(self.recent_goodput[-20:]))

    def rolling_empty(self) -> float:
        return 0.0 if not self.recent_empty else float(np.mean(self.recent_empty[-40:]))

    def step(self, env_I: float) -> dict:
        capacity = self.base_budget * float(np.clip(self.budget_mul, 0.05, 1.2)) * max(
            0.12, 1.0 - 0.26 * env_I
        )
        active = list(np.where(self.alive)[0])
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0:
            self.recent_goodput.append(0.0)
            return self._snap(0, 0, capacity, 0, 0)

        serve = int(min(demand, max(0, round(capacity))))
        flake = float(np.clip(0.05 + 0.12 * env_I, 0.04, 0.55))
        empty_p = float(np.clip(self.tool_empty, 0, 0.75))

        ok = fails = empties = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            if i < serve and self.rng.random() > flake:
                # served — but tool may return empty
                if self.rng.random() < empty_p:
                    empties += 1
                    fails += 1
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
                fails += 1
                self.fail[c] += 1
                self.recent_ok.append(0)
                self.recent_empty.append(0.0)
                self.retries = min(2.8, self.retries + 0.035)
                if self.fail[c] >= 7 and self.rng.random() < 0.28:
                    self.alive[c] = False

        if fails == 0:
            self.retries = max(0.0, self.retries - 0.07)
        if len(self.recent_ok) > 300:
            self.recent_ok = self.recent_ok[-300:]
        if len(self.recent_empty) > 200:
            self.recent_empty = self.recent_empty[-200:]

        gp = ok / self.n
        self.recent_goodput.append(gp)
        if len(self.recent_goodput) > 80:
            self.recent_goodput = self.recent_goodput[-80:]
        return self._snap(ok, fails, capacity, demand, empties)

    def _snap(self, ok, fails, capacity, demand, empties):
        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "rolling_empty": self.rolling_empty(),
            "n_alive": int(np.sum(self.alive)),
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "budget_mul": self.budget_mul,
            "tool_empty": self.tool_empty,
            "budget_remaining": float(np.clip(self.budget_mul * max(0.1, capacity / max(self.base_budget, 1)), 0, 1)),
            "ok": ok,
            "fails": fails,
            "empties": empties,
        }

    def quarantine_worst(self, k=1):
        idx = np.where(self.alive)[0]
        if len(idx) == 0:
            return
        for i in sorted(idx, key=lambda j: -self.fail[j])[:k]:
            self.alive[i] = False

    def revive(self, k=1):
        for i in np.where(~self.alive)[0][:k]:
            self.alive[i] = True
            self.fail[i] = 0


def week_schedule(rng: np.random.Generator):
    """
    Returns lists length 7*24: env_I, budget_mul, tool_empty, day_label, hour
    Realistic tough week — peaks, not annihilation.
    """
    env, bud, empty, day, hour = [], [], [], [], []
    for d, name in enumerate(DAYS):
        for h in range(STEPS_PER_DAY):
            # base diurnal: night quiet, business hours busier
            if h < 6:
                base_I, base_b = 0.85, 1.0
            elif h < 9:
                base_I, base_b = 1.15, 0.95
            elif h < 12:
                base_I, base_b = 1.35, 0.9
            elif h < 14:
                base_I, base_b = 1.25, 0.92
            elif h < 18:
                base_I, base_b = 1.45, 0.88
            else:
                base_I, base_b = 1.05, 0.98

            te = 0.04  # ambient empty tools

            if name == "Mon":
                # steady prod
                I = base_I + rng.normal(0, 0.05)
                b = base_b
            elif name == "Tue":
                # deploy day — afternoon thrash
                I = base_I + (0.55 if 13 <= h <= 17 else 0.1) + rng.normal(0, 0.06)
                b = base_b * (0.85 if 13 <= h <= 16 else 1.0)
                te = 0.08 if 13 <= h <= 17 else 0.05
            elif name == "Wed":
                # rate-limit storm mid-day to evening
                if 10 <= h <= 19:
                    I = 2.15 + 0.25 * np.sin((h - 10) / 3) + rng.normal(0, 0.08)
                    b = 0.55 + 0.1 * rng.random()
                else:
                    I = base_I + 0.15
                    b = 0.8
                te = 0.06
            elif name == "Thu":
                # flaky tools / empty responses (integration debt day)
                I = base_I + 0.25 + rng.normal(0, 0.07)
                b = base_b * 0.9
                te = 0.22 + (0.12 if 9 <= h <= 16 else 0.0)
            elif name == "Fri":
                # quota pinch + backlog (month-end vibes)
                I = base_I + 0.35 + (0.4 if 11 <= h <= 16 else 0.1)
                b = 0.45 + 0.15 * (h / 24)  # slowly recovers? or tight all day
                b = float(np.clip(0.42 + 0.02 * max(0, h - 14), 0.4, 0.75))
                te = 0.1
            elif name == "Sat":
                I = 0.95 + 0.15 * rng.random()
                b = 0.9
                te = 0.05
            else:  # Sun catch-up then calm
                if h < 14:
                    I = 1.55 + 0.2 * rng.random()
                    b = 0.75
                    te = 0.07
                else:
                    I = 1.05
                    b = 1.0
                    te = 0.04

            env.append(float(np.clip(I, 0.5, 2.6)))
            bud.append(float(np.clip(b, 0.35, 1.1)))
            empty.append(float(np.clip(te, 0, 0.5)))
            day.append(name)
            hour.append(h)
    return env, bud, empty, day, hour


def apply_plan(world: WeekWorld, plan) -> None:
    if plan.cool_retries:
        mul = 0.68 if plan.storm_active else 0.75
        world.retries = max(0.0, world.retries * mul)
    if plan.quarantine_k > 0:
        world.quarantine_worst(plan.quarantine_k)
    if plan.revive_k > 0:
        world.revive(plan.revive_k if plan.open_traffic or not plan.storm_active else min(1, plan.revive_k))
    if plan.concurrency_delta < 0:
        world.retries = max(0.0, world.retries + 0.025 * plan.concurrency_delta)


def run_arm(name: str, seed: int, use_engine: bool, storm_mode: str, sched) -> dict:
    env, bud, empty, days, hours = sched
    world = WeekWorld(rng=np.random.default_rng(seed))
    rows = []
    n = len(env)

    if not use_engine:
        for t in range(n):
            world.budget_mul = bud[t]
            world.tool_empty = empty[t]
            # baseline thrash grows with failures automatically
            m = world.step(env[t])
            # naive stampede under bad days
            if m["rolling_goodput"] < 0.25:
                world.retries = min(2.8, world.retries + 0.02)
            rows.append({**m, "env_I": env[t], "felt_I": env[t], "day": days[t], "hour": hours[t], "stab": None, "storm": False})
    else:
        k_rng = np.random.default_rng(seed + 33)
        agents = K.make_swarm(k_rng)
        paradox = K.Paradox(K.PROMOTED_DNA)
        paradox.install_drivers(agents)
        ambient = 0.0
        stab = 0.9
        prev = env[0]
        for t in range(n):
            world.budget_mul = bud[t]
            world.tool_empty = empty[t]
            d_env = env[t] - prev
            plan = plan_actions(
                stab,
                success_rate=world.rolling_success(),
                goodput=world.rolling_goodput(),
                env_load=env[t],
                thrash=world.retries + world.rolling_empty(),
                storm_mode=storm_mode,  # type: ignore[arg-type]
                d_env=d_env,
                budget_remaining=float(np.clip(bud[t], 0, 1)),
                target=TARGET,
            )
            felt = apply_shield(env[t], plan)
            m = world.step(felt)
            apply_plan(world, plan)

            I = to_interference(
                success_rate=world.rolling_success(),
                env_load=env[t],
                thrash=world.retries,
                empty_tool_rate=world.rolling_empty(),
                budget_remaining=float(np.clip(bud[t], 0, 1)),
            )
            # also blend from_api flavor
            I = 0.55 * I + 0.45 * from_api(
                world.rolling_goodput(), env[t], retries=world.retries, budget_remaining=bud[t]
            )
            I = float(np.clip(I, 0.4, 3.0))

            for a in agents:
                a.step(I, ambient, k_rng)
            ambient = 0.03 * float(np.mean([a.flux for a in agents]))
            paradox.hive_pair_churn(agents, k_rng)
            paradox.install_drivers(agents)
            stab = K.stability(agents)

            rows.append(
                {
                    **m,
                    "env_I": env[t],
                    "felt_I": felt,
                    "day": days[t],
                    "hour": hours[t],
                    "stab": stab,
                    "storm": plan.storm_active,
                    "note": plan.note,
                }
            )
            prev = env[t]

    gp = np.array([r["rolling_goodput"] for r in rows])
    alive = np.array([r["n_alive"] for r in rows], float)
    empty_r = np.array([r["rolling_empty"] for r in rows])

    by_day = {}
    for dname in DAYS:
        idx = [i for i, r in enumerate(rows) if r["day"] == dname]
        by_day[dname] = {
            "gp": float(np.mean(gp[idx])),
            "alive": float(np.mean(alive[idx])),
            "empty": float(np.mean(empty_r[idx])),
            "retries": float(np.mean([rows[i]["retries"] for i in idx])),
        }

    return {
        "name": name,
        "rows": rows,
        "gp_mean": float(np.mean(gp)),
        "gp_late": float(np.mean(gp[-STEPS_PER_DAY:])),  # Sunday
        "gp_min": float(np.min(gp)),
        "alive_mean": float(np.mean(alive)),
        "alive_min": float(np.min(alive)),
        "alive_end": float(alive[-1]),
        "empty_mean": float(np.mean(empty_r)),
        "retries_peak": float(np.max([r["retries"] for r in rows])),
        "storm_frac": float(np.mean([1.0 if r.get("storm") else 0.0 for r in rows])),
        "stab_mean": float(np.mean([r["stab"] for r in rows if r["stab"] is not None])) if use_engine else None,
        "by_day": by_day,
    }


def main() -> int:
    print("=" * 68)
    print(" TOUGH WEEK SIM — real-world-ish (no blackout nuke)")
    print(" Mon steady · Tue deploy · Wed 429 · Thu flaky tools · Fri quota")
    print(" Sat quiet · Sun catch-up  |  baseline vs engine vs storm_auto")
    print("=" * 68)

    seeds = [7, 11, 21, 42]
    arms = {"baseline": [], "engine": [], "storm": []}

    for seed in seeds:
        rng = np.random.default_rng(seed)
        sched = week_schedule(rng)
        b = run_arm("baseline", seed, False, "off", sched)
        e = run_arm("engine", seed + 1, True, "off", sched)
        s = run_arm("storm", seed + 2, True, "auto", sched)
        arms["baseline"].append(b)
        arms["engine"].append(e)
        arms["storm"].append(s)
        print(
            f"  seed={seed}  "
            f"base gp={b['gp_mean']:.3f} alive_end={b['alive_end']:.0f}  |  "
            f"eng {e['gp_mean']:.3f}/{e['alive_end']:.0f}  |  "
            f"storm {s['gp_mean']:.3f}/{s['alive_end']:.0f} storm%={100*s['storm_frac']:.0f}"
        )

    def M(arm, key):
        return float(np.mean([x[key] for x in arms[arm]]))

    def Mday(arm, day, key):
        return float(np.mean([x["by_day"][day][key] for x in arms[arm]]))

    print("\n[WEEK OVERALL]")
    for arm in ("baseline", "engine", "storm"):
        print(
            f"  {arm:10s}  gp_mean={M(arm,'gp_mean'):.3f}  gp_Sun={M(arm,'gp_late'):.3f}  "
            f"alive_mean={M(arm,'alive_mean'):.1f}  alive_end={M(arm,'alive_end'):.1f}  "
            f"empty={M(arm,'empty_mean'):.3f}  retries_pk={M(arm,'retries_peak'):.2f}  "
            f"storm%={100*M(arm,'storm_frac'):.0f}"
        )

    print("\n[BY DAY — goodput]")
    print(f"  {'day':5s}  {'base':>7s}  {'engine':>7s}  {'storm':>7s}  eng−base  storm−eng")
    for d in DAYS:
        bb, ee, ss = Mday("baseline", d, "gp"), Mday("engine", d, "gp"), Mday("storm", d, "gp")
        print(f"  {d:5s}  {bb:7.3f}  {ee:7.3f}  {ss:7.3f}  {ee-bb:+.3f}    {ss-ee:+.3f}")

    print("\n[BY DAY — alive]")
    print(f"  {'day':5s}  {'base':>7s}  {'engine':>7s}  {'storm':>7s}")
    for d in DAYS:
        print(
            f"  {d:5s}  {Mday('baseline',d,'alive'):7.1f}  "
            f"{Mday('engine',d,'alive'):7.1f}  {Mday('storm',d,'alive'):7.1f}"
        )

    print("\n[DELTAS]")
    print(f"  eng − base  week gp:  {M('engine','gp_mean')-M('baseline','gp_mean'):+.3f}")
    print(f"  storm − base week gp: {M('storm','gp_mean')-M('baseline','gp_mean'):+.3f}")
    print(f"  storm − eng  week gp: {M('storm','gp_mean')-M('engine','gp_mean'):+.3f}")
    print(f"  eng − base  end alive:  {M('engine','alive_end')-M('baseline','alive_end'):+.1f}")
    print(f"  storm − eng end alive:  {M('storm','alive_end')-M('engine','alive_end'):+.1f}")

    # worst day for baseline
    worst = min(DAYS, key=lambda d: Mday("baseline", d, "gp"))
    print(f"\n  Hardest day for baseline: {worst} (gp={Mday('baseline',worst,'gp'):.3f})")
    print(
        f"  That day eng={Mday('engine',worst,'gp'):.3f}  storm={Mday('storm',worst,'gp'):.3f}"
    )

    eng_wins = M("engine", "gp_mean") > M("baseline", "gp_mean") + 0.03
    storm_edge = M("storm", "gp_mean") >= M("engine", "gp_mean") - 0.01
    if eng_wins and M("storm", "gp_mean") > M("engine", "gp_mean") + 0.015:
        verdict = (
            "TOUGH_WEEK_HANDLED: engine clearly beats baseline; storm_auto adds edge on peak days. "
            "Fits a real production week without needing blackout training."
        )
    elif eng_wins:
        verdict = (
            "TOUGH_WEEK_HANDLED: classic engine is the workhorse for a hard week; "
            "storm_auto roughly ties (shell for peaks, not every hour)."
        )
    else:
        verdict = "UNEXPECTED: inspect day table."

    print(f"\n  VERDICT → {verdict}")

    # plot seed 21
    rng = np.random.default_rng(21)
    sched = week_schedule(rng)
    b = run_arm("b", 21, False, "off", sched)
    e = run_arm("e", 22, True, "off", sched)
    s = run_arm("s", 23, True, "auto", sched)
    x = np.arange(len(sched[0]))

    fig, axes = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    ax = axes[0]
    ax.plot(x, sched[0], color="#9b59b6", label="env I", lw=1.0)
    ax.plot(x, sched[1], color="#f39c12", label="budget mul", lw=1.0)
    ax.plot(x, sched[2], color="#e67e22", label="tool empty p", lw=1.0)
    for i, d in enumerate(DAYS):
        ax.axvline(i * STEPS_PER_DAY, color="#333", alpha=0.3, lw=0.8)
        ax.text(i * STEPS_PER_DAY + 2, 2.4, d, fontsize=8, color="#aaa")
    ax.set_ylabel("schedule")
    ax.set_title("Tough week (seed=21) — no blackout")
    ax.legend(fontsize=7, loc="upper right", ncol=3)
    ax.set_ylim(0, 2.7)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(x, [r["rolling_goodput"] for r in b["rows"]], color="#ff6b8a", label="baseline")
    ax2.plot(x, [r["rolling_goodput"] for r in e["rows"]], color="#5dffb0", label="engine")
    ax2.plot(x, [r["rolling_goodput"] for r in s["rows"]], color="#40d0ff", label="storm_auto", lw=1.4)
    ax2.set_ylabel("goodput")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)
    ax2.set_ylim(0, 1.05)

    ax3 = axes[2]
    ax3.plot(x, [r["n_alive"] / 28 for r in b["rows"]], color="#ff6b8a", label="alive base")
    ax3.plot(x, [r["n_alive"] / 28 for r in e["rows"]], color="#5dffb0", label="alive eng")
    ax3.plot(x, [r["n_alive"] / 28 for r in s["rows"]], color="#40d0ff", label="alive storm", lw=1.4)
    ax3.set_ylabel("alive frac")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)

    ax4 = axes[3]
    ax4.plot(x, [r["retries"] for r in b["rows"]], color="#ff6b8a", label="retries base")
    ax4.plot(x, [r["retries"] for r in e["rows"]], color="#5dffb0", label="retries eng")
    ax4.plot(x, [r["retries"] for r in s["rows"]], color="#40d0ff", label="retries storm", lw=1.4)
    storm_on = [0.5 if r.get("storm") else 0 for r in s["rows"]]
    ax4.fill_between(x, 0, storm_on, color="#40d0ff", alpha=0.15, label="shell on")
    ax4.set_ylabel("retry thrash")
    ax4.set_xlabel("step (24/day × 7)")
    ax4.legend(fontsize=7, ncol=2)
    ax4.grid(True, alpha=0.25)
    fig.tight_layout()
    png = OUT / "tough_week.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    # day bars
    fig2, ax = plt.subplots(figsize=(10, 5))
    xb = np.arange(len(DAYS))
    w = 0.25
    ax.bar(xb - w, [Mday("baseline", d, "gp") for d in DAYS], w, label="baseline", color="#ff6b8a")
    ax.bar(xb, [Mday("engine", d, "gp") for d in DAYS], w, label="engine", color="#5dffb0")
    ax.bar(xb + w, [Mday("storm", d, "gp") for d in DAYS], w, label="storm_auto", color="#40d0ff")
    ax.set_xticks(xb)
    ax.set_xticklabels(DAYS)
    ax.set_ylabel("mean goodput")
    ax.set_title("Tough week by day")
    ax.legend()
    ax.grid(True, alpha=0.25, axis="y")
    fig2.tight_layout()
    png2 = OUT / "tough_week_by_day.png"
    fig2.savefig(png2, dpi=120)
    plt.close(fig2)
    print(f"  plot → {png2}")

    out = {
        "proto": "tough_week_v1",
        "dna": "PROMOTED_FROZEN",
        "days": DAYS,
        "steps_per_day": STEPS_PER_DAY,
        "seeds": seeds,
        "overall": {
            arm: {
                "gp_mean": M(arm, "gp_mean"),
                "gp_late_sun": M(arm, "gp_late"),
                "alive_mean": M(arm, "alive_mean"),
                "alive_end": M(arm, "alive_end"),
                "empty_mean": M(arm, "empty_mean"),
                "retries_peak": M(arm, "retries_peak"),
                "storm_frac": M(arm, "storm_frac"),
            }
            for arm in arms
        },
        "by_day_gp": {
            arm: {d: Mday(arm, d, "gp") for d in DAYS} for arm in arms
        },
        "by_day_alive": {
            arm: {d: Mday(arm, d, "alive") for d in DAYS} for arm in arms
        },
        "deltas": {
            "eng_minus_base_gp": M("engine", "gp_mean") - M("baseline", "gp_mean"),
            "storm_minus_base_gp": M("storm", "gp_mean") - M("baseline", "gp_mean"),
            "storm_minus_eng_gp": M("storm", "gp_mean") - M("engine", "gp_mean"),
            "eng_minus_base_alive_end": M("engine", "alive_end") - M("baseline", "alive_end"),
            "storm_minus_eng_alive_end": M("storm", "alive_end") - M("engine", "alive_end"),
        },
        "hardest_baseline_day": worst,
        "verdict": verdict,
        "note": "Realistic tough week — not blackout. Soft Pack path validation.",
    }
    js = OUT / "tough_week_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
