# Real-world lab — Soft Pack nodes on real HTTP

All demos need **internet** + `numpy` + `matplotlib`.

## Scoreboard (last run on this machine)

| # | Demo | What | Baseline → Engine | Δ |
|---|------|------|-------------------|---|
| 1 | `http_fleet_demo.py` | Shared-budget HTTP workers | 0.387 → 0.815 | **+0.428** |
| 2 | `tool_fleet_demo.py` | Multi-tool agents (12 real endpoints) | 0.883 → 1.000 | **+0.117** |
| 3 | `job_queue_demo.py` | Queue + real HTTP jobs + re-queue | 0.819 → 1.000 | **+0.181** |
| 4 | `quota_hell_demo.py` | **Stress:** 20 workers, 48 steps, tight quota, multi-step storms | 0.109 → 0.195 | **+0.086** (+0.29 late); alive **0→20** |

**Quota hell:** target locked **0.92**. Kernel late **0.946**. Verdict **STRESS HANDLED**.

Re-runs will vary slightly (network). Direction should hold: engine calmer, often faster wall time.

## Run any demo

```bat
cd "…\INFINITY ENGINE KERNAL 1"
python real_world\http_fleet_demo.py
python real_world\tool_fleet_demo.py
python real_world\job_queue_demo.py
python real_world\quota_hell_demo.py
```

Open HTML from `real_world\out\`:
- `http_fleet_case_study.html`
- `tool_fleet_case_study.html`
- `job_queue_case_study.html`
- `quota_hell_case_study.html`

## Storm shell / hell lab (local R&D)

| Script | What |
|--------|------|
| `expand_l2_demo.py` | L2 mid-band flex |
| `hell_beacons_surge_demo.py` | Beacons + surge · hell matrix |
| `storm_surge_learn_cycles.py` | Shell v2 + 3-cycle learn |
| `toughen_then_hell_eval.py` | 3.0↔6.4 toughen ×3 → hell eval |
| `storm_mode_429_demo.py` | **Buyer path:** `storm_mode` actuate under 429 hell |

```bat
python real_world\storm_mode_429_demo.py
python real_world\hell_beacons_surge_demo.py
python real_world\storm_surge_learn_cycles.py
python real_world\toughen_then_hell_eval.py
```

Also mirrored on GitHub: `experiments/storm_shell/` in **paradox-engine**.

## Next: GitHub

See **`GITHUB_START.md`** in this folder — step-by-step first comment / PR path.

## Soft Pack link

https://blakesinger.gumroad.com/l/wcorn  
(Product sales; demos are your lab.)
