# Soft Pack — Integration (surface only)

Wire your system at two edges. **Do not open the kernel.**

```
your metrics  →  ingest  →  KERNEL_v1  →  actuate  →  your system
```

## 1. Ingest

**Input (examples):** rolling success rate, error rate, queue depth, 429 rate, env load score  
**Output:** interference `I` in roughly `0.4 … 3.0` (higher = harder day)

```python
from nodes.ingest import to_interference

I = to_interference(success_rate=0.61, env_load=1.4)
# or
I = to_interference(failure_rate=0.35, env_load=2.0, thrash=0.4)
```

## 2. Kernel step (use the frozen runner)

```python
import KERNEL_v1 as K
# make_swarm + Paradox + step loop — see nodes/engine_loop.py
```

Or call:

```python
from nodes.engine_loop import HealthEngine

eng = HealthEngine(seed=42)
out = eng.step(I=1.6)   # -> stability, actions hint
```

## 3. Actuate

**Input:** kernel `stability` (and optional your rolling success / env load)  
**Output:** shield load, quarantine N, revive N, cool retries, optional **storm shell**

```python
from nodes.actuate import plan_actions, apply_shield

plan = plan_actions(
    stability=0.91,
    success_rate=0.55,
    env_load=2.4,
    thrash=0.9,
    storm_mode="auto",   # off | auto | on
    budget_remaining=0.3,
)
# plan.shield_scale, plan.storm_active, plan.storm_scale, plan.felt_scale()
felt = apply_shield(env_load=2.4, plan=plan)
```

`storm_mode="auto"` deepens felt-load cut under high env/thrash (429 hell).  
DNA stays frozen — this is an actuate skin, not a second kernel.

```python
from nodes.engine_loop import HealthEngine
eng = HealthEngine(seed=42, storm_mode="auto")
out = eng.step_from_metrics(success_rate=0.5, env_load=2.6, thrash=1.0, goodput=0.2)
```

Apply `plan` in *your* code (kill worst workers, lower concurrency, etc.).

**429 hell demo:** `python real_world/storm_mode_429_demo.py`

## Performance claim (how to verify)

```bat
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
```

You should see baseline vs engine and a green Δ. That is the product surface.

## Support boundary

Install / run / “my metric doesn’t map” → OK.  
“Explain every DNA field” → out of Soft Pack scope (pilot or decline).
