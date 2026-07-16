# Eye of the Storm

**Product brand:** Eye of the Storm  
**Engine family (lab / suite):** Paradox Engine  

**Chaos can hit it. Chaos can’t own it.**  
**Nothing is unbreakable... But your system can't break this.**

A **health layer** for multi-agent fleets, worker queues, and API clients under **load thrash** — retries, tool flakes, 429 stampedes.

Not a chatbot. Not another agent framework. Not Cloudflare.  
**Complements** LangGraph / Temporal / your edge — it fills the gap when fleets thrash under load.

**Buy the pack ($149):** [Eye of the Storm on Gumroad](https://blakesinger.gumroad.com/l/wcorn)

**Free thrash note (3–5h hard cap):** what’s thrashing + any rates → one-page levers. No pitch deck. Gumroad message or open an issue titled `sample request`.

---

## What ships today (storefront)

| Pain | Proof | Baseline → Engine | Lift |
|------|-------|-------------------|------|
| Agent fleets die when tools flake | **A** | 0.474 → 0.695 success | **+0.221** |
| Worker queues stampede on retries | **B** | 0.510 → 0.743 success | **+0.232** |
| API clients melt under 429 thrash | **C** | 0.018 → 0.257 goodput | **+0.239** |

Kernel late stability ~**0.94–0.95** (target band ~0.92 — holds without locking at fake 1.0).

Public shorthand: **+0.22 / +0.23 / +0.24**. Seeded. **You re-run it.**

```bat
pip install -r REQUIREMENTS.txt
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
```

Open [`START_HERE.html`](START_HERE.html) or [`OPEN_THESE_PROOFS/`](OPEN_THESE_PROOFS/).

---

## One-sentence pitch

> When agents, workers, or API clients thrash under load, Eye of the Storm keeps real work alive and cools the stampede — measured, re-runnable.

---

## Suite vision (complement, don’t replace)

| Need | Use |
|------|-----|
| Who does what (graphs, roles, tools) | LangGraph / CrewAI / etc. |
| Durable jobs that survive crashes | Temporal / queues |
| **Fleet health under storms / thrash** | **Eye of the Storm (ships now)** |
| Edge volumetric DDoS | Cloudflare / Akamai / cloud shield |
| Answer faithfulness under multi-retrieval thrash | **Research module** (offline — not the paid zip yet) |

```
your agents / workers / APIs
        ↓ metrics
   Eye of the Storm health step
        ↓ actuate
shield · cool thrash · quarantine worst · revive when healthy
```

We pick at **components** of reliability problems (thrash, false confidence, dual evidence) — not slogans like “solve hallucinations” or “beat the edge.”

---

## Architecture (surface)

```
your metrics  →  ingest  →  KERNEL  →  actuate  →  your system
```

| Piece | Role |
|-------|------|
| **Ingest** | Failures / load → interference |
| **Kernel** | Health step (frozen contract) |
| **Actuate** | Shield, cool thrash, quarantine, revive |
| **Contract** | Target ~0.92 · soft ceiling ~0.97 (anti-lock) |

Wire-in: [`INTEGRATION.md`](INTEGRATION.md) · Plugins: [`plugins/README.md`](plugins/README.md)

```python
from plugins import Eye, HealthSnapshot

eye = Eye(seed=42, world="auto")
ctrl = eye.step(HealthSnapshot(success_rate=0.55, env_load=1.9, thrash=0.7))
# → max_concurrency, retry_budget, storm_active, felt_load_scale
```

---

## Product vs this repo

| | GitHub (this) | Gumroad Eye of the Storm |
|--|---------------|---------------------------|
| Proofs A/B/C | Yes | Yes + packaging |
| Kernel + ingest/actuate | Yes | Yes |
| Support | Issues / community | Personal license |
| Logic-loop / answer governor | **Research only** — not product claim | Not in v1 zip |
| Residual industrial DefenseStack | Lab / not storefront | Not in v1 zip |

---

## Research (honest, not sold yet)

We are **not** shipping “AI hallucination solved.”

We **are** decomposing one slice of reliability: multi-source grounding, false confidence, thrash-bounded revise, abstain when sources fight — the same control DNA as thrash Soft Pack, applied to claims.

See:

- [`experiments/research/HALLUCINATION_ASPECTS.md`](experiments/research/HALLUCINATION_ASPECTS.md) — components & negative space  
- [`experiments/research/LOGIC_LOOP.md`](experiments/research/LOGIC_LOOP.md) — status of the offline module  

When that module is product-ready, it becomes an optional suite piece — not a replacement for Soft Pack thrash.

---

## Names

| Layer | Name |
|-------|------|
| **What you buy** | **Eye of the Storm** |
| Engine family | Paradox Engine (lab / suite handle) |

“Paradox” appears in other products/games brands historically. We claim no affiliation. If the suite scales commercially, name clearance is a separate step. **Lead with Eye of the Storm on the buy button.**

---

## Quick start

```bat
pip install -r REQUIREMENTS.txt
python KERNEL_v1.py --status
python KERNEL_v1.py --demo 40
python -m plugins.examples.minimal_all
```

Requires: **Python 3.10+**, `numpy`, `matplotlib`.

---

## License

See `LICENSE`. Sales and personal license terms are on [Gumroad](https://blakesinger.gumroad.com/l/wcorn).

---

## Not claimed

Invincible systems · guaranteed SLA percentages · memory-corruption CVE theater · trading alpha · edge Tbps · “we solved hallucinations.”
