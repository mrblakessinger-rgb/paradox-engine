# Storm shell experiments (prototype)

Defense-stack lab on top of the **promoted** Paradox kernel.  
**Not** Soft Pack DNA promote. **Not** a second product.

## What’s here

| Script | What |
|--------|------|
| `expand_l2_demo.py` | Mid-band (L2) flex + soft edge absorb |
| `hell_beacons_surge_demo.py` | Beacons + surge shield · multi-scenario hell matrix |
| `storm_surge_learn_cycles.py` | Storm surge **shell v2** + 3-cycle Paradox learn |
| `toughen_then_hell_eval.py` | Train **3.0↔6.4** ramps ×3, then re-run hell suite |
| `storm_mode_429_demo.py` | **Buyer path:** `storm_mode` on actuate under synthetic 429 hell |
| `_annihilation_pass.py` | Cliff finder (I~7 / double-nuke) |

Results from the last local run are under `out/` (JSON + PNG).

## Product wire-in (main repo)

```python
from nodes.actuate import plan_actions, apply_shield
plan = plan_actions(stability, env_load=2.6, thrash=1.0, storm_mode=\"auto\")
felt = apply_shield(env_load, plan)
```

Or `HealthEngine(storm_mode=\"auto\")` in `nodes/engine_loop.py`.

## Run

```bat
pip install -r REQUIREMENTS.txt
cd experiments\storm_shell
python storm_mode_429_demo.py
python hell_beacons_surge_demo.py
```
