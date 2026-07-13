"""One-shot annihilation cliff finder."""
import json
from pathlib import Path

import numpy as np

import hell_beacons_surge_demo as H

OUT = Path(__file__).resolve().parent / "out"


def scen_nuke(t, steps, rng, I):
    return float(np.clip(7.0 + rng.normal(0, 0.5), 6.0, 9.0))


def scen_double_nuke(t, steps, rng, I):
    return float(np.clip(9.5 + rng.normal(0, 0.8), 8.0, 12.0))


H.SCENARIOS["annihilation"] = {
    "fn": scen_nuke,
    "noise_amp": 3.0,
    "shock": 0.20,
    "hive": True,
    "start_hurt": 0.35,
}
H.SCENARIOS["double_nuke"] = {
    "fn": scen_double_nuke,
    "noise_amp": 4.0,
    "shock": 0.35,
    "hive": False,
    "start_hurt": 0.45,
}

seeds = [7, 21, 42, 99]
stacks = ["baseline", "surge_only", "beacons_only", "surge_beacons", "full_defense"]
report = {}

for scen in ("annihilation", "double_nuke"):
    print(f"\n=== {scen} ===")
    report[scen] = {}
    for stack in stacks:
        rs = [
            H.run_episode(scenario=scen, stack=stack, seed=s, steps=100) for s in seeds
        ]
        a = H.aggregate(rs)
        report[scen][stack] = a
        print(
            f"  {stack:14s} late={a['late_mean']:.3f} min={a['min_mean']:.3f} "
            f"edge={a['edge_mean']:.3f} hard%={100 * a['hard_rate']:.0f} "
            f"soft%={100 * a['soft_rate']:.0f} hold%={100 * a['hold_rate']:.0f}"
        )

path = OUT / "annihilation_cliff.json"
path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(f"\n→ {path}")
