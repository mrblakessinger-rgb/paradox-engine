# Infinity Engine Soft Pack v1

**Price:** $149 personal · **Built:** 2026-07-14  
**Promise:** Measured health control for multi-agent / worker systems under load storms.  
**Doctrine:** You buy the lift. Internals stay sealed.

## OPEN THE PROOFS FIRST (already in this zip)

You do **not** have to take our word for it. Charts + HTML case studies are included.

1. Double-click **`START_HERE.html`**  
   **or** open folder **`OPEN_THESE_PROOFS/`**

| File | What you see |
|------|----------------|
| `OPEN_THESE_PROOFS/A_agent_fleet.html` | Baseline **0.47** → Engine **0.69** (**+0.22**) |
| `OPEN_THESE_PROOFS/B_job_queue.html` | Baseline **0.51** → Engine **0.74** (**+0.23**) |
| `OPEN_THESE_PROOFS/C_rate_limit.html` | Goodput **0.02** → **0.25** (**+0.24**) |
| `OPEN_THESE_PROOFS/*_chart.png` | The actual comparison plots |

Full runners (re-generate numbers yourself) live under `portfolio/proof_*`.

## Then re-run (optional, proves it on your machine)

```bat
pip install -r REQUIREMENTS.txt
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
start out\proof_a_case_study.html
```

Expect ~**+0.22** again. Same for B and C.

## What's inside

| Path | What |
|------|------|
| **`START_HERE.html`** | Front door — links to all three proofs |
| **`OPEN_THESE_PROOFS/`** | Pre-built HTML + PNG results (no Python needed) |
| `portfolio/proof_a_*` | Full agent-fleet proof (code + out/) |
| `portfolio/proof_b_*` | Full job-queue proof |
| `portfolio/proof_c_*` | Full API rate-limit proof |
| `KERNEL_v1.py` | Frozen kernel |
| `nodes/` | Ingest + actuate + HealthEngine wire-in |
| `plugins/` | Drop-in adapters: fleet, queue, API, LangGraph, CrewAI |
| `portfolio/ONE_PAGER.html` | Shareable one-pager |
| `INTEGRATION.md` | Wire your metrics |
| `LICENSE_PERSONAL.txt` | Personal-use license |

## What is NOT inside (on purpose)

- Training / DNA breeding lab
- Architecture deep-dives
- Consulting hours
- Live host OS control (CPU/GPU/RAM drivers) — optional sandbox is lab-only; Soft Pack stays intent-level via storm/recovery/horizon

## Health stack included (v1 refresh)

- Auto storm pack + beacons
- Credit loop (forecast vs actual)
- Recovery desire after load drop
- Horizon scout (leading indicators / pre-arm)
- Desire band via `target_coherence` (Soft Pack default remains conservative; lab may run higher)

## Support boundary

OK: install, open proofs, re-run, map success rate → ingest  
Out of scope: every internal lever / re-derive DNA

## Layout note

Proof runners expect `KERNEL_v1.py` at pack root (two levels up from `portfolio/proof_*/`).
