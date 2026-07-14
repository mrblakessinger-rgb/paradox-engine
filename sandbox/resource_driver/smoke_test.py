"""python -m sandbox.resource_driver.smoke_test"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nodes.engine_loop import HealthEngine
from sandbox.resource_driver import ResourceDriver, SimSensors


def main() -> int:
    eng = HealthEngine(seed=1, storm_mode="auto", credit_loop=False, target=0.95)
    sensors = SimSensors()
    driver = ResourceDriver(sensors=sensors)
    sensors.set(cpu_util=0.92, mem_pressure=0.78, gpu_util=0.85)
    out = eng.step_from_metrics(
        success_rate=0.35,
        env_load=2.1,
        thrash=0.9,
        goodput=0.18,
        budget_remaining=0.45,
        empty_tool_rate=0.12,
        queue_pressure=0.6,
        arrival_rate=1.4,
    )
    res = driver.step(out["plan"])
    print("storm", out["storm_active"], "pre_arm", out.get("pre_arm"), "risk", out.get("surge_risk"))
    print("intent", res.intent.as_dict())
    print("actions", [a.name for a in res.actions])
    print("dry_run", res.dry_run)
    assert res.dry_run is True
    assert res.intent.active()
    print("OK sandbox smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
