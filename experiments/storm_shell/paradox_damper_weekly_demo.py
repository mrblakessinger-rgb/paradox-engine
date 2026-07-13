"""
Paradox live damper + weekly arsenal drill
==========================================
Two-week calm-ish schedule so the **weekly_arsenal_drill** is visible,
plus a short real thrash window in week 2.

Arms:
  A) engine storm=auto, weekly_drill ON, Paradox damper (default HealthEngine)
  B) engine storm=auto, weekly_drill OFF
  C) engine storm=off (no shell/beacons/drill)

  python real_world/paradox_damper_weekly_demo.py
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

from nodes.engine_loop import HealthEngine
from nodes.actuate import apply_shield, WEEKLY_DRILL_OFFSET, WEEKLY_DRILL_DURATION

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

STEPS = 168 * 2  # two weeks


def schedule(t: int):
    """Mostly moderate; week2 has a Thu thrash spike."""
    week = t // 168
    hod = t % 168
    day = hod // 24
    hour = hod % 24
    env = 1.2 + 0.15 * (1 if 9 <= hour <= 17 else 0)
    thr = 0.25
    gp = 0.50
    br = 0.85
    # week 2 Thursday (day 3) afternoon thrash
    if week == 1 and day == 3 and 12 <= hour <= 18:
        env = 2.25
        thr = 1.05
        gp = 0.16
        br = 0.4
    return env, thr, gp, br


def run_arm(name: str, seed: int, storm_mode: str, weekly_drill: bool):
    eng = HealthEngine(
        seed=seed,
        storm_mode=storm_mode,  # type: ignore[arg-type]
        weekly_drill=weekly_drill,
        steps_per_week=168,
    )
    rows = []
    for t in range(STEPS):
        env, thr, gp, br = schedule(t)
        out = eng.step_from_metrics(
            success_rate=gp,
            env_load=env,
            thrash=thr,
            goodput=gp,
            budget_remaining=br,
        )
        rows.append(
            {
                "t": t,
                "env": env,
                "storm": out["storm_active"],
                "reason": out["storm_reason"],
                "drill": out["weekly_drill"],
                "damper": out["damper_live"],
                "beacon": out["beacon_active"],
                "stab": out["stability"],
            }
        )
    storm = np.array([r["storm"] for r in rows])
    drill = np.array([r["drill"] for r in rows])
    damp = np.array([r["damper"] for r in rows])
    # drill windows
    d_idx = np.where(drill)[0]
    return {
        "name": name,
        "rows": rows,
        "storm_frac": float(np.mean(storm)),
        "drill_frac": float(np.mean(drill)),
        "drill_steps": int(np.sum(drill)),
        "storm_during_drill": float(np.mean(storm[d_idx])) if len(d_idx) else 0.0,
        "damper_mean": float(np.mean(damp)),
        "damper_drill": float(np.mean(damp[d_idx])) if len(d_idx) else 0.0,
        "damper_calm": float(np.mean(damp[~drill & ~storm])) if np.any(~drill & ~storm) else float(np.mean(damp)),
        "reasons_on_drill": list({rows[i]["reason"] for i in d_idx[:5]}) if len(d_idx) else [],
        "stab_mean": float(np.mean([r["stab"] for r in rows])),
    }


def main():
    print("=" * 64)
    print(" PARADOX DAMPER + WEEKLY ARSENAL DRILL (2 weeks)")
    print(f" drill offset={WEEKLY_DRILL_OFFSET} dur={WEEKLY_DRILL_DURATION} / 168")
    print("=" * 64)

    seeds = [7, 21, 42]
    arms = {
        "A_default": [],
        "B_no_drill": [],
        "C_storm_off": [],
    }
    for seed in seeds:
        arms["A_default"].append(run_arm("A", seed, "auto", True))
        arms["B_no_drill"].append(run_arm("B", seed + 1, "auto", False))
        arms["C_storm_off"].append(run_arm("C", seed + 2, "off", False))

    def M(arm, k):
        return float(np.mean([x[k] for x in arms[arm]]))

    print("\n[SUMMARY]")
    for arm in arms:
        print(
            f"  {arm:12s}  drill_steps={M(arm,'drill_steps'):.0f}  "
            f"storm_on_drill={100*M(arm,'storm_during_drill'):.0f}%  "
            f"damp_drill={M(arm,'damper_drill'):.3f}  damp_calm={M(arm,'damper_calm'):.3f}  "
            f"storm_frac={100*M(arm,'storm_frac'):.0f}%  stab={M(arm,'stab_mean'):.3f}"
        )

    a = arms["A_default"][0]
    print(f"\n  sample drill reasons (seed7): {a['reasons_on_drill']}")
    print(
        f"  damper lift on drill (A): "
        f"{M('A_default','damper_drill') - M('A_default','damper_calm'):+.3f}"
    )

    ok = (
        M("A_default", "drill_steps") >= 16
        and M("A_default", "storm_during_drill") >= 0.95
        and M("A_default", "damper_drill") > M("A_default", "damper_calm") + 0.05
    )
    print(f"\n  VERDICT → {'PASS' if ok else 'CHECK'} — weekly drill arms arsenal; Paradox raises damper")

    # plot
    r = arms["A_default"][0]["rows"]
    x = np.arange(len(r))
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    ax = axes[0]
    ax.plot(x, [row["env"] for row in r], color="#9b59b6", label="env")
    ax.fill_between(
        x,
        0,
        [1.5 if row["drill"] else 0 for row in r],
        color="#f39c12",
        alpha=0.35,
        label="weekly drill",
    )
    ax.fill_between(
        x,
        0,
        [1.0 if row["storm"] else 0 for row in r],
        color="#40d0ff",
        alpha=0.25,
        label="storm active",
    )
    ax.axvline(168, color="#666", ls="--", lw=1)
    ax.set_ylabel("env / flags")
    ax.set_title("Paradox weekly arsenal drill + damper (2 weeks)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)

    ax2 = axes[1]
    ax2.plot(x, [row["damper"] for row in r], color="#2ecc71", label="live damper")
    ax2.axhline(1.45, color="#888", ls=":", label="floor")
    ax2.axhline(2.28, color="#888", ls="--", label="ceiling")
    ax2.set_ylabel("damper")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.25)

    ax3 = axes[2]
    ax3.plot(x, [row["stab"] for row in r], color="#5dffb0", label="stability")
    ax3.axhline(0.92, color="#3498db", ls="--")
    ax3.set_ylabel("stability")
    ax3.set_xlabel("step (168 = 1 week)")
    ax3.legend(fontsize=8)
    ax3.grid(True, alpha=0.25)
    fig.tight_layout()
    png = OUT / "paradox_damper_weekly.png"
    fig.savefig(png, dpi=120)
    plt.close(fig)
    print(f"  plot → {png}")

    out = {
        "proto": "paradox_damper_weekly_v1",
        "steps": STEPS,
        "weekly_drill": {
            "offset": WEEKLY_DRILL_OFFSET,
            "duration": WEEKLY_DRILL_DURATION,
            "reason": "weekly_arsenal_drill",
        },
        "summary": {
            arm: {
                k: M(arm, k)
                for k in (
                    "drill_steps",
                    "storm_during_drill",
                    "damper_drill",
                    "damper_calm",
                    "storm_frac",
                    "stab_mean",
                )
            }
            for arm in arms
        },
        "pass": ok,
    }
    js = OUT / "paradox_damper_weekly_results.json"
    js.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"  json → {js}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
