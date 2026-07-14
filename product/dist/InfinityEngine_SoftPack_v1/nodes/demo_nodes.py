"""
Smoke test for public nodes (ingest → engine → actuate).

  python nodes/demo_nodes.py
  python -m nodes.demo_nodes
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodes.actuate import apply_shield, plan_actions
from nodes.engine_loop import HealthEngine, smoke_demo
from nodes.ingest import from_api, from_fleet, from_queue, to_interference


def main() -> int:
    print("=" * 60)
    print(" NODES SMOKE — ingest / engine / actuate")
    print("=" * 60)

    print("\n[ingest]")
    print(f"  fleet  I = {from_fleet(0.55, 1.8):.3f}")
    print(f"  queue  I = {from_queue(0.50, 1.6, queue_depth=90):.3f}")
    print(f"  api    I = {from_api(0.20, 2.0, retries=0.8):.3f}")
    print(f"  generic I = {to_interference(success_rate=0.7, env_load=1.0):.3f}")

    print("\n[engine]")
    eng = HealthEngine(seed=7)
    for env in (0.8, 1.5, 2.4, 2.9):
        I = from_fleet(0.55, env)
        out = eng.step(I, success_rate=0.55)
        plan = out["plan"]
        felt = apply_shield(env, plan)
        print(
            f"  env={env:.1f} I={I:.2f} stab={out['stability']:.3f} "
            f"shield={plan.shield_scale:.2f} felt={felt:.2f} "
            f"q={plan.quarantine_k} r={plan.revive_k} ({plan.note})"
        )

    print("\n[smoke_demo]")
    r = smoke_demo(steps=50, seed=42)
    print(f"  late stability = {r['late_stability']:.4f}  (target {r['target']})")
    print(f"  mean / min     = {r['mean_stability']:.4f} / {r['min_stability']:.4f}")

    ok = r["late_stability"] >= 0.85
    print("\n" + ("  PASS" if ok else "  REVIEW"))
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
