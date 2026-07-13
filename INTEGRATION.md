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

## 3. Actuate (+ automatic storm pack)

**Input:** kernel `stability` + optional success / env load / thrash / budget  
**Output:** shield, quarantine, revive, cool retries, **storm pack when extreme**

**You do not flip a storm switch in production.**  
`HealthEngine` defaults to `storm_mode="auto"`. Paradox treats the storm shell as
an **arsenal** for extreme circumstances (wisdom: `storm_arsenal`).

**Paradox also owns the live damper dial** (up in storm/drill, ease in calm; band ~1.45–2.28).  
**Once per week** it runs an **arsenal drill** (`weekly_arsenal_drill`) so the pack
stays practiced even in mild weeks — shell + beacons + damper upshift, still automatic.

### Auto trigger points (any → arm shell)

| Signal | Enter | Exit (all + 3 calm steps) |
|--------|-------|---------------------------|
| env_load | ≥ 1.75 | < 1.45 |
| thrash / retries | ≥ 0.75 | < 0.40 |
| budget_remaining | < 0.50 (+ stress) | ≥ 0.65 |
| goodput | < 0.20 (+ stress) | ≥ 0.28 |
| env spike | Δenv ≥ 0.20 | — |
| kernel I | ≥ 2.15 | < 1.85 |
| empty_tool_rate | ≥ 0.18 (+ stress) | low |

```python
from nodes.engine_loop import HealthEngine
from nodes.actuate import apply_shield

eng = HealthEngine(seed=42)  # storm auto by default
out = eng.step_from_metrics(
    success_rate=0.5, env_load=2.2, thrash=0.9, goodput=0.18, budget_remaining=0.4
)
plan = out["plan"]
# plan.storm_active, plan.storm_reason, plan.felt_scale()
felt = apply_shield(2.2, plan)
```

Override only if needed: `storm_mode="off"` or `"on"`.  
DNA stays frozen — actuate skin, not a second kernel.

**Demos:** `python real_world/storm_mode_429_demo.py` · `python real_world/tough_week_sim.py`

## Performance claim (how to verify)

```bat
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
```

You should see baseline vs engine and a green Δ. That is the product surface.

## Support boundary

Install / run / “my metric doesn’t map” → OK.  
“Explain every DNA field” → out of Soft Pack scope (pilot or decline).
