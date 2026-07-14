"""
Smoke examples — no external frameworks required.

  python -m plugins.examples.minimal_all
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plugins import Eye, HealthSnapshot
from plugins.adapters.api_client import ApiClientPlugin
from plugins.adapters.fleet import FleetPlugin
from plugins.adapters.queue import QueuePlugin
from plugins.adapters.langgraph import eye_gate_node


def demo_eye() -> None:
    print("\n=== Eye core ===")
    eye = Eye(seed=1, world="auto")
    for env, sr, thr in [(1.0, 0.8, 0.1), (2.2, 0.45, 0.9), (1.2, 0.7, 0.2)]:
        c = eye.step(HealthSnapshot(success_rate=sr, env_load=env, thrash=thr))
        print(
            f"  env={env:.1f} sr={sr:.2f} → stab={c.stability:.3f} "
            f"conc={c.max_concurrency} pace={c.request_pace:.2f} "
            f"storm={c.storm_active} note={c.note[:40]!r}"
        )


def demo_fleet() -> None:
    print("\n=== FleetPlugin (Problem X) ===")
    fleet = FleetPlugin(n_agents=20, seed=2)
    for step in range(5):
        # simulate half-fail under load
        ok, fail = (14, 6) if step < 2 else (8, 12)
        ctrl = fleet.observe(successes=ok, failures=fail, env_load=1.5 + 0.3 * step, empty_tools=2)
        applied = fleet.apply(ctrl)
        print(
            f"  t={step} active={applied['active']} storm={applied['storm_active']} "
            f"Q={applied['quarantined'][:3]} R={applied['revived'][:3]}"
        )


def demo_queue() -> None:
    print("\n=== QueuePlugin (Problem Y) ===")
    workers = {"n": 12}

    def set_w(n: int) -> None:
        workers["n"] = n

    q = QueuePlugin(capacity=80, base_workers=12, set_workers=set_w, seed=3)
    for depth, sr in [(20, 0.75), (60, 0.5), (90, 0.35), (40, 0.65)]:
        ctrl = q.tick(depth=depth, success_rate=sr, env_load=1.0 + depth / 50, thrash=depth / 100)
        applied = q.apply(ctrl)
        print(f"  depth={depth} workers={workers['n']} retry={applied['retry_budget']:.2f} storm={applied['storm_active']}")


def demo_api() -> None:
    print("\n=== ApiClientPlugin (Problem Z) ===")
    api = ApiClientPlugin(base_rps=20, seed=4)
    ctrl = api.observe(ok=30, err=5, status_429=15, latency_p95=2.5)
    s = api.apply_summary(ctrl)
    print(f"  delay={s['pace_delay_s']:.3f}s retries={s['max_retries']} storm={s['storm_active']} pace={s['request_pace']:.2f}")


def demo_langgraph_node() -> None:
    print("\n=== LangGraph-style node (no langgraph install) ===")
    node = eye_gate_node(seed=5)
    state = {
        "success_rate": 0.5,
        "env_load": 2.0,
        "thrash": 0.8,
        "tool_calls": 40,
        "tool_errors": 12,
    }
    out = node(state)
    print(f"  storm={out['storm_active']} max_conc={out['max_concurrency']} pause={out['pause_new_work']}")


def main() -> int:
    print("Eye of the Storm — plugin smoke")
    demo_eye()
    demo_fleet()
    demo_queue()
    demo_api()
    demo_langgraph_node()
    print("\nOK — plugins ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
