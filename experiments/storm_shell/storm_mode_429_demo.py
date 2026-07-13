"""
Storm mode under synthetic 429 hell
===================================
Compares three arms on a shared-budget API client world:

  A) baseline — no health layer (stampede)
  B) engine   — Soft Pack path, storm_mode=off  (classic cool/shield)
  C) storm    — same DNA, storm_mode=auto       (surge shell when env/thrash spike)

Schedule: calm → 429 hell plateaus → flicker → recover (several times).
DNA: PROMOTED frozen. No promote.

  python real_world/storm_mode_429_demo.py
"""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K
from nodes.actuate import apply_shield, plan_actions
from nodes.ingest import from_api

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TARGET = K.TARGET_STABILITY


class RateLimitWorld:
    """Shared budget clients — 429-style capacity cut + retry thrash."""

    def __init__(self, n_clients: int = 28, budget: float = 11.0, rng: np.random.Generator | None = None):
        self.n_clients = n_clients
        self.base_budget = budget
        self.rng = rng or np.random.default_rng(0)
        self.alive = np.ones(n_clients, dtype=bool)
        self.client_fail = np.zeros(n_clients, dtype=int)
        self.recent_ok: list[int] = []
        self.recent_goodput: list[float] = []
        self.retries = 0.0
        self.ok_total = 0
        self.attempts = 0

    def rolling_success(self) -> float:
        if not self.recent_ok:
            return 0.5
        return float(np.mean(self.recent_ok[-80:]))

    def rolling_goodput(self) -> float:
        if not self.recent_goodput:
            return 0.25
        return float(np.mean(self.recent_goodput[-20:]))

    def budget_frac(self, interference: float) -> float:
        """How much of base budget remains under this env (0..1-ish)."""
        return float(max(0.05, 1.0 - 0.32 * interference))

    def step(self, interference: float) -> dict:
        capacity = self.base_budget * self.budget_frac(interference)
        active = list(np.where(self.alive)[0])
        extras = int(round(self.retries * len(active)))
        demand = len(active) + extras
        if demand <= 0:
            self.recent_goodput.append(0.0)
            return {
                "rolling_success": self.rolling_success(),
                "rolling_goodput": self.rolling_goodput(),
                "n_alive": 0,
                "retries": self.retries,
                "capacity": capacity,
                "demand": 0,
                "budget_remaining": 0.0,
            }

        serve = int(min(demand, max(0, round(capacity))))
        # 429 hell: flake rises hard with I
        flake = float(np.clip(0.08 + 0.18 * interference, 0.06, 0.78))

        ok = 0
        fails = 0
        for i in range(demand):
            c = int(active[i % len(active)])
            self.attempts += 1
            if i < serve and self.rng.random() > flake:
                ok += 1
                self.ok_total += 1
                self.client_fail[c] = max(0, self.client_fail[c] - 1)
                self.recent_ok.append(1)
            else:
                fails += 1
                self.client_fail[c] += 1
                self.recent_ok.append(0)
                self.retries = min(3.0, self.retries + 0.045)
                if self.client_fail[c] >= 6 and self.rng.random() < 0.40:
                    self.alive[c] = False

        if fails == 0:
            self.retries = max(0.0, self.retries - 0.09)

        if len(self.recent_ok) > 400:
            self.recent_ok = self.recent_ok[-400:]

        step_gp = ok / self.n_clients
        self.recent_goodput.append(step_gp)
        if len(self.recent_goodput) > 80:
            self.recent_goodput = self.recent_goodput[-80:]

        br = float(np.clip(capacity / max(self.base_budget, 1e-6), 0.0, 1.0))
        return {
            "rolling_success": self.rolling_success(),
            "rolling_goodput": self.rolling_goodput(),
            "step_goodput": step_gp,
            "n_alive": int(np.sum(self.alive)),
            "retries": self.retries,
            "capacity": capacity,
            "demand": demand,
            "budget_remaining": br,
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


def hell_429_schedule(steps: int, rng: np.random.Generator) -> list[float]:
    """
    Several 429 waves: floor ~1.2, climb toward 2.9–3.0, flicker, recover.
    (Env units for the *world*; storm shell keys off this.)
    """
    out = []
    I = 1.2
    for t in range(steps):
        u = (t % 40) / 40.0
        block = t // 40
        if block % 2 == 0:
            # hell plateau blocks
            if u < 0.15:
                I = float(np.clip(1.1 + rng.normal(0, 0.05), 0.8, 1.6))
            elif u < 0.55:
                I = float(np.clip(2.75 + rng.normal(0, 0.08), 2.3, 3.0))
            elif u < 0.75:
                I = float(rng.choice([2.2, 2.6, 2.95, 1.5]))
            else:
                I = float(np.clip(1.3 + rng.normal(0, 0.1), 0.9, 2.0))
        else:
            # irregular re-attacks
            r = rng.random()
            if r < 0.25:
                I = float(rng.uniform(2.6, 3.0))
            elif r < 0.45:
                I = float(rng.uniform(2.0, 2.5))
            else:
                I = float(np.clip(1.2 + rng.normal(0, 0.12), 0.7, 2.2))
        out.append(I)
    return out


def apply_plan(world: RateLimitWorld, plan) -> None:
    if plan.cool_retries:
        # storm shell: slightly stronger thrash cool, not a death spiral
        mul = 0.64 if plan.storm_active else 0.70
        world.retries = max(0.0, world.retries * mul)
    if plan.quarantine_k > 0:
        world.quarantine_worst(plan.quarantine_k)
    if plan.revive_k > 0:
        k = plan.revive_k
        if plan.storm_active and not plan.open_traffic:
            k = min(k, 1)  # still revive under storm, just slower
        world.revive(k)
    if plan.concurrency_delta < 0 and world.retries > 0:
        world.retries = max(0.0, world.retries + 0.03 * plan.concurrency_delta)


def run_arm(
    *,
    name: str,
    seed: int,
    schedule: list[float],
    use_engine: bool,
    storm_mode: str,
) -> dict:
    rng = np.random.default_rng(seed)
    world = RateLimitWorld(rng=np.random.default_rng(seed + 3))
    rows = []

    if not use_engine:
        for env_I in schedule:
            m = world.step(env_I)
            rows.append({**m, "env_I": env_I, "felt_I": env_I, "stab": None, "storm": False, "note": "baseline"})
    else:
        k_rng = np.random.default_rng(seed + 50)
        agents = K.make_swarm(k_rng)
        paradox = K.Paradox(K.PROMOTED_DNA)
        paradox.install_drivers(agents)
        ambient = 0.0
        stab = 0.88
        prev_env = schedule[0]
        for env_I in schedule:
            d_env = env_I - prev_env
            plan = plan_actions(
                stab,
                success_rate=world.rolling_success(),
                goodput=world.rolling_goodput(),
                env_load=env_I,
                thrash=world.retries,
                storm_mode=storm_mode,  # type: ignore[arg-type]
                d_env=d_env,
                budget_remaining=world.budget_frac(env_I),
                target=TARGET,
            )
            felt = apply_shield(env_I, plan)
            m = world.step(felt)
            apply_plan(world, plan)

            I = from_api(
                world.rolling_goodput(),
                env_I,
                retries=world.retries,
                budget_remaining=world.budget_frac(env_I),
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
                    "storm_scale": plan.storm_scale,
                    "shield_scale": plan.shield_scale,
                    "felt_scale": plan.felt_scale(),
                    "note": plan.note,
                }
            )
            prev_env = env_I

    gp = np.array([r["rolling_goodput"] for r in rows], float)
    alive = np.array([r["n_alive"] for r in rows], float)
    late_n = max(1, len(rows) // 5)
    storm_frac = float(np.mean([1.0 if r.get("storm") else 0.0 for r in rows]))
    return {
        "name": name,
        "rows": rows,
        "gp_mean": float(np.mean(gp)),
        "gp_late": float(np.mean(gp[-late_n:])),
        "gp_min": float(np.min(gp)),
        "alive_late": float(np.mean(alive[-24:])) if len(alive) >= 24 else float(np.mean(alive)),
        "alive_min": float(np.min(alive)),
        "storm_frac": storm_frac,
        "retries_late": float(np.mean([r["retries"] for r in rows[-late_n:]])),
    }


def main() -> int:
    print("=" * 64)
    print(" STORM MODE — synthetic 429 hell (DNA frozen)")
    print("=" * 64)

    seeds = [7, 13, 21, 42]
    steps = 120
    arms_agg = {"baseline": [], "engine_off": [], "storm_auto": []}

    for seed in seeds:
        rng = np.random.default_rng(seed)
        sch = hell_429_schedule(steps, rng)
        b = run_arm(name="baseline", seed=seed, schedule=sch, use_engine=False, storm_mode="off")
        e = run_arm(name="engine_off", seed=seed + 1, schedule=sch, use_engine=True, storm_mode="off")
        s = run_arm(name="storm_auto", seed=seed + 2, schedule=sch, use_engine=True, storm_mode="auto")
        arms_agg["baseline"].append(b)
        arms_agg["engine_off"].append(e)
        arms_agg["storm_auto"].append(s)
        print(
            f"  seed={seed}  base gp_late={b['gp_late']:.3f} alive={b['alive_late']:.1f}  |  "
            f"eng {e['gp_late']:.3f}/{e['alive_late']:.1f}  |  "
            f"storm {s['gp_late']:.3f}/{s['alive_late']:.1f} storm%={100*s['storm_frac']:.0f}"
        )

    def mean_key(arm: str, key: str) -> float:
        return float(np.mean([x[key] for x in arms_agg[arm]]))

    print("\n[SUMMARY across seeds]")
    for arm in ("baseline", "engine_off", "storm_auto"):
        print(
            f"  {arm:12s}  gp_mean={mean_key(arm,'gp_mean'):.3f}  "
            f"gp_late={mean_key(arm,'gp_late'):.3f}  "
            f"alive_late={mean_key(arm,'alive_late'):.1f}  "
            f"storm%={100*mean_key(arm,'storm_frac'):.0f}"
        )

    d_eng = mean_key("engine_off", "gp_late") - mean_key("baseline", "gp_late")
    d_storm = mean_key("storm_auto", "gp_late") - mean_key("baseline", "gp_late")
    d_shell = mean_key("storm_auto", "gp_late") - mean_key("engine_off", "gp_late")
    d_alive = mean_key("storm_auto", "alive_late") - mean_key("engine_off", "alive_late")
    print(f"\n  Δ eng−base late goodput   : {d_eng:+.3f}")
    print(f"  Δ storm−base late goodput : {d_storm:+.3f}")
    print(f"  Δ storm−eng late goodput  : {d_shell:+.3f}")
    print(f"  Δ storm−eng late alive    : {d_alive:+.1f}")

    # plot seed 13 triple
    rng = np.random.default_rng(13)
    sch = hell_429_schedule(steps, rng)
    b = run_arm(name="baseline", seed=13, schedule=sch, use_engine=False, storm_mode="off")
    e = run_arm(name="engine_off", seed=14, schedule=sch, use_engine=True, storm_mode="off")
    s = run_arm(name="storm_auto", seed=15, schedule=sch, use_engine=True, storm_mode="auto")

    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    x = np.arange(steps)
    ax = axes[0]
    ax.plot(x, [r["rolling_goodput"] for r in b["rows"]], color="#ff6b8a", label="baseline", lw=1.4)
    ax.plot(x, [r["rolling_goodput"] for r in e["rows"]], color="#5dffb0", label="engine storm=off", lw=1.4)
    ax.plot(x, [r["rolling_goodput"] for r in s["rows"]], color="#40d0ff", label="engine storm=auto", lw=1.6)
    ax.set_ylabel("goodput")
    ax.set_title("Storm mode under synthetic 429 hell (seed=13 schedule)")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, alpha=0.25)
    ax.set_ylim(0, 1.05)

    ax2 = axes[1]
    ax2.plot(x, sch, color="#c090ff", label="env_I", lw=1.2)
    ax2.plot(x, [r["felt_I"] for r in e["rows"]], color="#5dffb0", alpha=0.8, label="felt eng", lw=1.0)
    ax2.plot(x, [r["felt_I"] for r in s["rows"]], color="#40d0ff", label="felt storm", lw=1.3)
    ax2.set_ylabel("I / felt")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)

    ax3 = axes[2]
    ax3.plot(x, [r["n_alive"] / 28 for r in b["rows"]], color="#ff6b8a", label="alive base")
    ax3.plot(x, [r["n_alive"] / 28 for r in e["rows"]], color="#5dffb0", label="alive eng")
    ax3.plot(x, [r["n_alive"] / 28 for r in s["rows"]], color="#40d0ff", label="alive storm")
    storm_on = [1.0 if r.get("storm") else 0.0 for r in s["rows"]]
    ax3.fill_between(x, 0, storm_on, color="#40d0ff", alpha=0.15, label="storm shell on")
    ax3.set_ylabel("alive frac")
    ax3.set_xlabel("step")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)
    ax3.set_ylim(0, 1.05)

    fig.tight_layout()
    png = OUT / "storm_mode_429.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"\n  plot → {png}")

    out = {
        "proto": "storm_mode_429_v1",
        "dna": "PROMOTED_FROZEN",
        "seeds": seeds,
        "steps": steps,
        "summary": {
            arm: {
                "gp_mean": mean_key(arm, "gp_mean"),
                "gp_late": mean_key(arm, "gp_late"),
                "alive_late": mean_key(arm, "alive_late"),
                "storm_frac": mean_key(arm, "storm_frac"),
            }
            for arm in arms_agg
        },
        "delta": {
            "eng_minus_base_gp_late": d_eng,
            "storm_minus_base_gp_late": d_storm,
            "storm_minus_eng_gp_late": d_shell,
            "storm_minus_eng_alive_late": d_alive,
        },
        "api": {
            "plan_actions_storm_mode": ["off", "auto", "on"],
            "HealthEngine_storm_mode": True,
            "apply_shield_uses_felt_scale": True,
        },
        "note": "Section 6 next build — storm_mode actuate skin + 429 hell demo",
    }
    js = OUT / "storm_mode_429_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
