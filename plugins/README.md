# Eye of the Storm — Plugins

**Drop-in health control** for fleets, queues, API clients, LangGraph, CrewAI.

```
your system metrics  →  plugin  →  Eye (kernel)  →  ControlHints  →  your actuators
```

No hard dependencies on LangGraph / CrewAI / httpx. Import only what you use.

---

## 30-second start

```python
import sys
sys.path.insert(0, r"path\to\paradox-engine")

from plugins import Eye, HealthSnapshot

eye = Eye(seed=42)  # world="auto"|"fleet"|"queue"|"api"
ctrl = eye.step(HealthSnapshot(
    success_rate=0.55,
    env_load=1.9,
    thrash=0.7,
))

print(ctrl.max_concurrency, ctrl.retry_budget, ctrl.storm_active)
print(ctrl.felt_load_scale, ctrl.note)
# optional after you applied controls:
eye.feedback(goodput=0.5, alive_frac=0.8)
```

Smoke all adapters:

```bat
cd paradox-engine
python -m plugins.examples.minimal_all
```

---

## Problems → plugins

| Problem | Plugin | What you wire |
|---------|--------|----------------|
| **X** Agent fleets die on flaky tools | `FleetPlugin` | report OK/fail · apply quarantine/revive |
| **Y** Worker queues stampede | `QueuePlugin` | depth + success · set workers / retry budget |
| **Z** API 429 thrash | `ApiClientPlugin` | ok/err/429 · pace delay + max retries |
| LangGraph graphs thrash | `eye_gate_node` / `EyeStormCallback` | state metrics in · controls on state |
| CrewAI crews thrash | `EyeStormCrewGuard` | after_tasks · allow_next_wave |
| httpx / HTTP loops | `EyeStormSession` | auto pace between requests |

---

## ControlHints (what you get back)

| Field | Use it to… |
|-------|------------|
| `max_concurrency` | Cap workers / agents |
| `retry_budget` | Scale max retries (0..1 × your base) |
| `request_pace` | Multiplier on RPS (delay = 1/(base_rps×pace)) |
| `felt_load_scale` | Shield: multiply felt env / admission |
| `cool_retries` | Flatten retry storms |
| `quarantine_k` / `revive_k` | Drop worst / bring back |
| `storm_active` | Extreme mode — pause non-critical work |
| `open_traffic` / `recovery_active` | Open up after the storm |
| `should_pause_new_work()` | Easy boolean gate |

---

## Adapter cheatsheets

### Fleet (X)

```python
from plugins.adapters.fleet import FleetPlugin

fleet = FleetPlugin(n_agents=20)
# … agents ran tools …
ctrl = fleet.observe(successes=11, failures=9, env_load=2.0, empty_tools=3)
fleet.apply(ctrl)          # quarantines / revives slots
run_only = fleet.active_ids()
```

### Queue (Y)

```python
from plugins.adapters.queue import QueuePlugin

q = QueuePlugin(capacity=100, base_workers=16, set_workers=my_pool.resize)
ctrl = q.tick(depth=70, success_rate=0.42, env_load=2.1, thrash=1.0)
q.apply(ctrl)
```

### API (Z)

```python
from plugins.adapters.api_client import ApiClientPlugin

api = ApiClientPlugin(base_rps=20)
api.record(ok=True, status=200)
api.record(ok=False, status=429)
ctrl = api.observe()  # uses window tallies
time.sleep(api.pace_delay(ctrl))
retries = api.max_retries(5, ctrl)
```

### LangGraph

```python
from plugins.adapters.langgraph import eye_gate_node

graph.add_node("eye_storm", eye_gate_node())
# state should include success_rate / env_load / thrash / tool_errors …
# node writes: max_concurrency, retry_budget, storm_active, pause_new_work, eye_storm{}
```

### CrewAI

```python
from plugins.adapters.crewai import EyeStormCrewGuard

guard = EyeStormCrewGuard()
ctrl = guard.after_tasks(ok=6, fail=4, env_load=1.8)
if not guard.allow_next_wave(ctrl):
    defer_next_batch()
```

---

## Design rules

1. **Kernel stays frozen** — plugins only use `HealthEngine` + ingest/actuate.  
2. **Hints not hostages** — you apply controls in *your* runtime.  
3. **Missing metrics OK** — fill what you have.  
4. **Not in buyer theory dump** — this is wire-in, not DNA tour.  
5. **Trading lab is separate** — not these plugins.

---

## Files

```
plugins/
  core.py           Eye / EyeOfTheStorm
  types.py          HealthSnapshot, ControlHints
  adapters/
    fleet.py
    queue.py
    api_client.py
    langgraph.py
    crewai.py
    httpx_client.py
  examples/
    minimal_all.py
```
