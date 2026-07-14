# Resource driver sandbox

**Fork:** host CPU / GPU / RAM control lives **here**, not in KERNEL DNA or Soft Pack body.

See `../FORK.md` for the frozen boundary.

## Quick use (dry-run)

```python
from nodes.engine_loop import HealthEngine
from sandbox.resource_driver import ResourceDriver, SimSensors

eng = HealthEngine(storm_mode="auto", credit_loop=True, target=0.95)
sensors = SimSensors()
driver = ResourceDriver(sensors=sensors)  # dry_run=True by default

sensors.set(cpu_util=0.9, mem_pressure=0.7)
out = eng.step_from_metrics(env_load=2.0, thrash=0.8, success_rate=0.4, budget_remaining=0.5)
result = driver.step(out["plan"])
print(result.as_dict())  # intents + proposed actions, nothing applied
```

## Layout

| File | Role |
|------|------|
| `intents.py` | Abstract `ResourceIntent` + map from `ActionPlan` |
| `sensors.py` | `HostSnapshot`, `SimSensors`, optional `PsutilSensors` |
| `driver.py` | Dry-run mapper + safety rails |
| `__init__.py` | Public exports |

## Live mode

`DriverConfig(dry_run=False, live_enabled=True)` is a **stub**. Real cgroup / CUDA / process limits are intentionally not implemented until:

1. Sim pressure exams pass  
2. Dry-run logs reviewed  
3. Explicit allowlist + fail-closed host policy  

## Soft Pack

Do **not** ship live host control in default Soft Pack zip. Optional add-on later.
