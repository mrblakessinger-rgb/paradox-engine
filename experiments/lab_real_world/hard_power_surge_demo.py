"""
Hard power surge simulation
===========================
Models a utility-style event on a shared API/worker fleet:

  1) Calm baseline load
  2) HARD POWER SURGE — sudden multi-step capacity collapse + I spike
     (brownout → near blackout → partial grid recovery flicker)
  3) Sustained aftershock thrash
  4) Recovery window

Arms:
  A) baseline — no health layer
  B) engine storm_mode=off
  C) engine storm_mode=auto  (surge shell)

DNA: PROMOTED frozen.

  python real_world/hard_power_surge_demo.py
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
from nodes.ingest import from_api

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = K.TARGET_STABILITY


class SurgeWorld:
    """
    Shared-budget clients under a power-grid style capacity multiplier.
    env_I = interference/demand stress
    power = 1.0 normal, ~0 under blackout (multiplies capacity)
    """

    def __init__(self, n_clients: int = 32, budget: float = 14.0, rng: np.random.Generator | None = None):
        self.n_clients = n_clients
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n_clients, dtype=bool)
        self.client_fail = np.zeros(n_clients, dtype=int)
        self.recent_ok: list[int] = []
        self.recent_goodput: list[float] = []
        self.retries = 0.0
        self.power = 1.0  # set by schedule each step

    def rolling_success(self) -> float:
        if not self.recent_ok:
            return 0.55
        return float(np.mean(self.recent_ok[-80:]))

    def rolling_goodput(self) -> float:
        if not self.recent_goodput:
            return 0.3
        return float(np.mean(self.recent_goodput[-24:]))

    def step(self, interference: float) -> dict:
        # capacity = budget * power * (1 - 0.22*I)  — surge kills power first
        cap_scale = float(np.clip(self.power, 0.0, 1.0)) * max(0.02, 1.0 - 0.22 * interference)
        capacity = self.base_budget * cap_scale
        active = list(np.where(self.alive)[0])
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0 or capacity < 0.05:
            # blackout: everything fails, thrash explodes if still "trying"
            if demand > 0 and self.power < 0.15:
                self.retries = min(3.5, self.retries + 0.12)
                for _ in range(min(demand, len(active) or 1)):
                    self.recent_ok.append(0)
                # kill some clients that keep hammering dead grid
                for c in active[: max(1, len(active) // 8)]:
                    self.client_fail[c] += 2
                    if self.client_fail[c] >= 5 and self.rng.random() < 0.5:
                        self.alive[c] = False
            self.recent_goodput.append(0.0)
            if len(self.recent_goodput) > 100:
                self.recent_goodput = self.recent_goodput[-100:]
            return {
                "rolling_success": self.rolling_success(),
                "rolling_goodput": self.rolling_goodput(),
                "n_alive": int(np.sum(self.alive)),
                "retries": self.retries,
                "capacity": capacity,
                "demand": demand,
                "power": self.power,
                "budget_remaining": float(np.clip(cap_scale, 0, 1)),
            }

        serve = int(min(demand, max(0, round(capacity))))
        # under low power, flake skyrockets (brownout errors)
        flake = float(
            np.clip(0.06 + 0.12 * interference + 0.55 * (1.0 - self.power), 0.05, 0.92)
        )

        ok = fails = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            if i < serve and self.rng.random() > flake:
                ok += 1
                self.client_fail[c] = max(0, self.client_fail[c] - 1)
                self.recent_ok.append(1)
            else:
                fails += 1
                self.client_fail[c] += 1
                self.recent_ok.append(0)
                self.retries = min(3.5, self.retries + 0.05)
                if self.client_fail[c] >= 6 and self.rng.random() < 0.42:
                    self.alive[c] = False

        if fails == 0 and self.power > 0.7:
            self.retries = max(0.0, self.retries - 0.10)

        if len(self.recent_ok) > 400:
            self.recent_ok = self.recent_ok[-400:]
        step_gp = ok / self.n_clients
        self.recent_goodput.append(step_gp)
        if len(self.recent_goodput) > 100:
            self.recent_goodput = self.recent_goodput[-100:]

        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "step_goodput": step_gp,
            "n_alive": int(np.sum(self.alive)),
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "power": self.power,
            "budget_remaining": float(np.clip(cap_scale, 0, 1)),
            "ok": ok,
            "fails": fails,
        }

    def quarantine_worst(self, k: int = 1):
        alive_idx = np.where(self.alive)[0]
        if len(alive_idx) == 0:
            return
        order = sorted(alive_idx, key=lambda i: -self.client_fail[i])
        for i in order[:k]:
            self.alive[i] = False

    def revive(self, k: int = 1):
        dead = np.where(~self.alive)[0]
        for i in dead[:k]:
            self.alive[i] = True
            self.client_fail[i] = 0


def power_surge_timeline(steps: int = 140) -> tuple[list[float], list[float], list[str]]:
    """
    Returns env_I, power, phase labels per step.
    Hard surge: power drops to near-zero for a block, I spikes, then flicker recovery.
    """
    env, power, phase = [], [], []
    for t in range(steps):
        if t < 20:
            # calm
            env.append(1.15)
            power.append(1.0)
            phase.append("calm")
        elif t < 28:
            # warning brownout
            env.append(1.8 + 0.05 * (t - 20))
            power.append(0.55 - 0.03 * (t - 20))
            phase.append("brownout")
        elif t < 48:
            # HARD POWER SURGE / near blackout
            env.append(2.95)
            # residual flicker on the dead bus
            p = 0.04 + 0.06 * ((t % 3) == 0)
            power.append(float(p))
            phase.append("SURGE")
        elif t < 62:
            # partial restore with thrash (grid unstable)
            env.append(2.4)
            power.append(0.35 + 0.15 * np.sin((t - 48) * 0.9))
            phase.append("aftershock")
        elif t < 78:
            # second spike (recloser fail)
            env.append(2.85)
            power.append(0.08 if (t % 2 == 0) else 0.22)
            phase.append("SURGE2")
        elif t < 100:
            # recovery climb
            env.append(1.6)
            power.append(min(1.0, 0.45 + 0.025 * (t - 78)))
            phase.append("recover")
        else:
            # settle
            env.append(1.2)
            power.append(1.0)
            phase.append("settle")
    return env, power, phase


def apply_plan(world: SurgeWorld, plan) -> None:
    if plan.cool_retries:
        mul = 0.60 if plan.storm_active else 0.72
        # under blackout, cool harder — stop hammering dead grid
        if world.power < 0.2:
            mul = min(mul, 0.50)
        world.retries = max(0.0, world.retries * mul)
    if plan.quarantine_k > 0:
        world.quarantine_worst(plan.quarantine_k)
    if plan.revive_k > 0:
        # don't revive into blackout
        if world.power >= 0.25:
            k = plan.revive_k
            if plan.storm_active and world.power < 0.6:
                k = min(k, 1)
            world.revive(k)
    if plan.concurrency_delta < 0 and world.retries > 0:
        world.retries = max(0.0, world.retries + 0.04 * plan.concurrency_delta)


def run_arm(
    *,
    name: str,
    seed: int,
    env_sched: list[float],
    power_sched: list[float],
    use_engine: bool,
    storm_mode: str,
) -> dict:
    world = SurgeWorld(rng=np.random.default_rng(seed))
    rows = []
    steps = len(env_sched)

    if not use_engine:
        for t in range(steps):
            world.power = power_sched[t]
            m = world.step(env_sched[t])
            rows.append(
                {
                    **m,
                    "env_I": env_sched[t],
                    "felt_I": env_sched[t],
                    "stab": None,
                    "storm": False,
                    "note": "baseline",
                }
            )
    else:
        k_rng = np.random.default_rng(seed + 77)
        agents = K.make_swarm(k_rng)
        paradox = K.Paradox(K.PROMOTED_DNA)
        paradox.install_drivers(agents)
        ambient = 0.0
        stab = 0.88
        prev_env = env_sched[0]
        for t in range(steps):
            env_I = env_sched[t]
            world.power = power_sched[t]
            d_env = env_I - prev_env
            # treat low power as extreme thrash/env for shell
            thrash_sig = world.retries + (1.0 - world.power) * 1.4
            plan = plan_actions(
                stab,
                success_rate=world.rolling_success(),
                goodput=world.rolling_goodput(),
                env_load=env_I + (1.0 - world.power) * 1.2,
                thrash=thrash_sig,
                storm_mode=storm_mode,  # type: ignore[arg-type]
                d_env=d_env + (0.0 if t == 0 else (power_sched[t - 1] - world.power)),
                budget_remaining=float(np.clip(world.power * max(0.05, 1.0 - 0.2 * env_I), 0, 1)),
                target=TARGET,
            )
            # felt demand stress — shell cuts; power still multiplies real capacity
            felt = apply_shield(env_I, plan)
            m = world.step(felt)
            apply_plan(world, plan)

            I = from_api(
                world.rolling_goodput(),
                env_I + (1.0 - world.power),
                retries=world.retries,
                budget_remaining=float(np.clip(world.power, 0, 1)),
            )
            for a in agents:
                a.step(I, ambient, k_rng)
            ambient = 0.03 * float(np.mean([a.flux for a in agents]))
            paradox.hive_pair_churn(agents, k_rng)
            paradox.install_drivers(agents)
            stab = K.stability(agents)

            rows.append(
                {
                    **m,
                    "env_I": env_I,
                    "felt_I": felt,
                    "stab": stab,
                    "storm": plan.storm_active,
                    "note": plan.note,
                    "felt_scale": plan.felt_scale(),
                }
            )
            prev_env = env_I

    gp = np.array([r["rolling_goodput"] for r in rows], float)
    alive = np.array([r["n_alive"] for r in rows], float)
    power = np.array([r["power"] for r in rows], float)

    def window(mask: np.ndarray, arr: np.ndarray) -> float:
        if not np.any(mask):
            return float("nan")
        return float(np.mean(arr[mask]))

    phases = np.array([r.get("_phase", "") for r in rows])  # filled by caller optional
    return {
        "name": name,
        "rows": rows,
        "gp_mean": float(np.mean(gp)),
        "gp_late": float(np.mean(gp[-max(1, len(gp) // 5) :])),
        "gp_min": float(np.min(gp)),
        "alive_late": float(np.mean(alive[-20:])),
        "alive_min": float(np.min(alive)),
        "alive_end": float(alive[-1]),
        "storm_frac": float(np.mean([1.0 if r.get("storm") else 0.0 for r in rows])),
        "retries_peak": float(np.max([r["retries"] for r in rows])),
        "gp_during_surge": None,  # set below
        "alive_during_surge": None,
        "gp_recover": None,
        "alive_recover": None,
    }


def annotate_phases(rows: list, phases: list[str]) -> None:
    for r, p in zip(rows, phases):
        r["_phase"] = p


def phase_metrics(result: dict, phases: list[str]) -> dict:
    rows = result["rows"]
    gp = np.array([r["rolling_goodput"] for r in rows])
    alive = np.array([r["n_alive"] for r in rows], float)
    ph = np.array(phases)
    out = {}
    for name in ("calm", "brownout", "SURGE", "aftershock", "SURGE2", "recover", "settle"):
        m = ph == name
        if np.any(m):
            out[name] = {
                "gp": float(np.mean(gp[m])),
                "alive": float(np.mean(alive[m])),
                "n": int(np.sum(m)),
            }
    # combined hard surge
    hard = (ph == "SURGE") | (ph == "SURGE2")
    out["hard_surge"] = {
        "gp": float(np.mean(gp[hard])) if np.any(hard) else float("nan"),
        "alive": float(np.mean(alive[hard])) if np.any(hard) else float("nan"),
        "min_alive": float(np.min(alive[hard])) if np.any(hard) else float("nan"),
    }
    return out


def main() -> int:
    print("=" * 68)
    print(" HARD POWER SURGE SIM — brownout → blackout → aftershock → recover")
    print(" DNA: PROMOTED frozen · arms: baseline | engine | storm_auto")
    print("=" * 68)

    env_sched, power_sched, phases = power_surge_timeline(140)
    seeds = [7, 13, 21, 42]

    agg = {"baseline": [], "engine_off": [], "storm_auto": []}
    phase_agg = {a: [] for a in agg}

    for seed in seeds:
        b = run_arm(
            name="baseline",
            seed=seed,
            env_sched=env_sched,
            power_sched=power_sched,
            use_engine=False,
            storm_mode="off",
        )
        e = run_arm(
            name="engine_off",
            seed=seed + 1,
            env_sched=env_sched,
            power_sched=power_sched,
            use_engine=True,
            storm_mode="off",
        )
        s = run_arm(
            name="storm_auto",
            seed=seed + 2,
            env_sched=env_sched,
            power_sched=power_sched,
            use_engine=True,
            storm_mode="auto",
        )
        for res in (b, e, s):
            annotate_phases(res["rows"], phases)
        pb, pe, ps = phase_metrics(b, phases), phase_metrics(e, phases), phase_metrics(s, phases)
        agg["baseline"].append(b)
        agg["engine_off"].append(e)
        agg["storm_auto"].append(s)
        phase_agg["baseline"].append(pb)
        phase_agg["engine_off"].append(pe)
        phase_agg["storm_auto"].append(ps)

        print(
            f"  seed={seed}  "
            f"base end_alive={b['alive_end']:.0f} gp_late={b['gp_late']:.3f}  |  "
            f"eng {e['alive_end']:.0f}/{e['gp_late']:.3f}  |  "
            f"storm {s['alive_end']:.0f}/{s['gp_late']:.3f}  "
            f"surge_alive storm={ps['hard_surge']['alive']:.1f} eng={pe['hard_surge']['alive']:.1f} base={pb['hard_surge']['alive']:.1f}"
        )

    def mkey(arm, key):
        return float(np.mean([x[key] for x in agg[arm]]))

    def mphase(arm, phase, key):
        return float(np.mean([x[phase][key] for x in phase_agg[arm]]))

    print("\n[OVERALL]")
    for arm in agg:
        print(
            f"  {arm:12s}  gp_mean={mkey(arm,'gp_mean'):.3f}  gp_late={mkey(arm,'gp_late'):.3f}  "
            f"alive_end={mkey(arm,'alive_end'):.1f}  alive_min={mkey(arm,'alive_min'):.1f}  "
            f"retries_peak={mkey(arm,'retries_peak'):.2f}  storm%={100*mkey(arm,'storm_frac'):.0f}"
        )

    print("\n[BY PHASE — mean goodput / alive]")
    print(f"  {'phase':12s}  {'base gp/al':>14s}  {'eng gp/al':>14s}  {'storm gp/al':>14s}")
    for ph in ("calm", "brownout", "SURGE", "aftershock", "SURGE2", "recover", "settle"):
        print(
            f"  {ph:12s}  "
            f"{mphase('baseline',ph,'gp'):.3f}/{mphase('baseline',ph,'alive'):5.1f}  "
            f"{mphase('engine_off',ph,'gp'):.3f}/{mphase('engine_off',ph,'alive'):5.1f}  "
            f"{mphase('storm_auto',ph,'gp'):.3f}/{mphase('storm_auto',ph,'alive'):5.1f}"
        )

    print("\n[HARD SURGE WINDOW (SURGE+SURGE2)]")
    for arm in agg:
        print(
            f"  {arm:12s}  gp={mphase(arm,'hard_surge','gp'):.3f}  "
            f"alive={mphase(arm,'hard_surge','alive'):.1f}  "
            f"min_alive={mphase(arm,'hard_surge','min_alive'):.1f}"
        )

    print("\n[DELTAS late goodput / end alive]")
    print(f"  eng − base:   gp {mkey('engine_off','gp_late')-mkey('baseline','gp_late'):+.3f}  "
          f"alive {mkey('engine_off','alive_end')-mkey('baseline','alive_end'):+.1f}")
    print(f"  storm − base: gp {mkey('storm_auto','gp_late')-mkey('baseline','gp_late'):+.3f}  "
          f"alive {mkey('storm_auto','alive_end')-mkey('baseline','alive_end'):+.1f}")
    print(f"  storm − eng:  gp {mkey('storm_auto','gp_late')-mkey('engine_off','gp_late'):+.3f}  "
          f"alive {mkey('storm_auto','alive_end')-mkey('engine_off','alive_end'):+.1f}")

    # narrative verdict
    base_dead = mkey("baseline", "alive_end") < 4
    storm_best = mkey("storm_auto", "alive_end") >= mkey("engine_off", "alive_end") - 0.5
    if base_dead and mkey("storm_auto", "alive_end") > mkey("baseline", "alive_end") + 5:
        verdict = (
            "SURGE_HANDLED_PARTIAL: baseline fleet largely dies in blackout thrash; "
            "health layer + storm shell keeps more clients alive into recovery. "
            "Goodput near zero during hard blackout is expected (no power = no capacity)."
        )
    elif mkey("storm_auto", "gp_late") > mkey("engine_off", "gp_late") + 0.02:
        verdict = "STORM_HELPS_RECOVERY: shell improves post-surge goodput vs classic engine."
    else:
        verdict = "MIXED: inspect phase table — blackout physics dominate mid-surge."

    print(f"\n  VERDICT → {verdict}")

    # plot seed 13
    b = run_arm(name="b", seed=13, env_sched=env_sched, power_sched=power_sched, use_engine=False, storm_mode="off")
    e = run_arm(name="e", seed=14, env_sched=env_sched, power_sched=power_sched, use_engine=True, storm_mode="off")
    s = run_arm(name="s", seed=15, env_sched=env_sched, power_sched=power_sched, use_engine=True, storm_mode="auto")

    fig, axes = plt.subplots(4, 1, figsize=(11, 10), sharex=True)
    x = np.arange(len(env_sched))
    # power
    ax = axes[0]
    ax.fill_between(x, power_sched, color="#f39c12", alpha=0.35, label="grid power")
    ax.plot(x, env_sched, color="#9b59b6", label="env I", lw=1.2)
    for t0, t1, c, lab in [
        (20, 28, "#e67e22", "brownout"),
        (28, 48, "#c0392b", "HARD SURGE"),
        (62, 78, "#922b21", "SURGE2"),
        (78, 100, "#3498db", "recover"),
    ]:
        ax.axvspan(t0, t1, color=c, alpha=0.12)
    ax.set_ylabel("power / I")
    ax.set_title("Hard power surge timeline")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_ylim(0, 3.2)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(x, [r["rolling_goodput"] for r in b["rows"]], color="#ff6b8a", label="baseline")
    ax2.plot(x, [r["rolling_goodput"] for r in e["rows"]], color="#5dffb0", label="engine")
    ax2.plot(x, [r["rolling_goodput"] for r in s["rows"]], color="#40d0ff", label="storm_auto", lw=1.5)
    ax2.set_ylabel("goodput")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)
    ax2.set_ylim(0, 1.05)

    ax3 = axes[2]
    ax3.plot(x, [r["n_alive"] / 32 for r in b["rows"]], color="#ff6b8a", label="alive base")
    ax3.plot(x, [r["n_alive"] / 32 for r in e["rows"]], color="#5dffb0", label="alive eng")
    ax3.plot(x, [r["n_alive"] / 32 for r in s["rows"]], color="#40d0ff", label="alive storm", lw=1.5)
    storm_on = [1.0 if r.get("storm") else 0.0 for r in s["rows"]]
    ax3.fill_between(x, 0, storm_on, color="#40d0ff", alpha=0.12, label="shell on")
    ax3.set_ylabel("alive frac")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)
    ax3.set_ylim(0, 1.05)

    ax4 = axes[3]
    ax4.plot(x, [r["retries"] for r in b["rows"]], color="#ff6b8a", label="retries base")
    ax4.plot(x, [r["retries"] for r in e["rows"]], color="#5dffb0", label="retries eng")
    ax4.plot(x, [r["retries"] for r in s["rows"]], color="#40d0ff", label="retries storm", lw=1.5)
    ax4.set_ylabel("retry thrash")
    ax4.set_xlabel("step")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.25)

    fig.tight_layout()
    png = OUT / "hard_power_surge.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "proto": "hard_power_surge_v1",
        "dna": "PROMOTED_FROZEN",
        "timeline": {
            "calm": "0-19 power=1",
            "brownout": "20-27 power→~0.3",
            "HARD_SURGE": "28-47 power~0.04-0.10",
            "aftershock": "48-61 unstable ~0.35",
            "SURGE2": "62-77 second spike",
            "recover": "78-99 power climb",
            "settle": "100-139 power=1",
        },
        "seeds": seeds,
        "overall": {
            arm: {
                "gp_mean": mkey(arm, "gp_mean"),
                "gp_late": mkey(arm, "gp_late"),
                "alive_end": mkey(arm, "alive_end"),
                "alive_min": mkey(arm, "alive_min"),
                "retries_peak": mkey(arm, "retries_peak"),
                "storm_frac": mkey(arm, "storm_frac"),
            }
            for arm in agg
        },
        "hard_surge": {
            arm: {
                "gp": mphase(arm, "hard_surge", "gp"),
                "alive": mphase(arm, "hard_surge", "alive"),
                "min_alive": mphase(arm, "hard_surge", "min_alive"),
            }
            for arm in agg
        },
        "phase_gp_alive": {
            arm: {
                ph: {
                    "gp": mphase(arm, ph, "gp"),
                    "alive": mphase(arm, ph, "alive"),
                }
                for ph in ("calm", "brownout", "SURGE", "aftershock", "SURGE2", "recover", "settle")
            }
            for arm in agg
        },
        "deltas": {
            "eng_minus_base_gp_late": mkey("engine_off", "gp_late") - mkey("baseline", "gp_late"),
            "storm_minus_base_gp_late": mkey("storm_auto", "gp_late") - mkey("baseline", "gp_late"),
            "storm_minus_eng_gp_late": mkey("storm_auto", "gp_late") - mkey("engine_off", "gp_late"),
            "storm_minus_eng_alive_end": mkey("storm_auto", "alive_end") - mkey("engine_off", "alive_end"),
        },
        "verdict": verdict,
    }
    js = OUT / "hard_power_surge_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
