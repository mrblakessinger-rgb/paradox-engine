# Paradox Engine

**Self-stabilizing health layer for multi-agent and multi-worker systems under load storms.**

Performance first. Internals sealed.  
Not a chatbot. Not a full agent framework.  
A **health controller** that holds a target band under thrash — storms, retries, rate-limit stampedes — without locking at perfect 1.0.

**Soft Pack (paid, optional):** [Gumroad — $149](https://blakesinger.gumroad.com/l/wcorn)  
Same core demos + packaging; Gumroad is the supported product surface.

---

## One-sentence pitch

> Paradox Engine keeps multi-agent / multi-process systems near a target health band under random load spikes — without constant human babysitting.

---

## Measured demos (re-run on your machine)

| Proof | World | Lift |
|-------|--------|------|
| **A** | Agent fleet / flaky tools | **+0.22** success |
| **B** | Job / worker queue storms | **+0.23** success |
| **C** | API rate-limit thrash | **+0.24** goodput |

Open proofs **without running Python first:**

1. Open `START_HERE.html`  
2. Or browse `OPEN_THESE_PROOFS/`

Re-run:

```bat
pip install -r REQUIREMENTS.txt
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
start out\proof_a_case_study.html
```

Same pattern for `proof_b_job_queue` and `proof_c_rate_limit`.

---

## Architecture (surface only)

```
your metrics  →  ingest  →  KERNEL (Paradox + hive)  →  actuate  →  your system
```

| Piece | Role |
|-------|------|
| **Ingest** | Failures / load → interference I |
| **Kernel** | Swarm health step + hive churn + promoted DNA |
| **Actuate** | Shield load, cool thrash, quarantine worst, revive when healthy |
| **Contract** | Target ~0.92 · soft ceiling 0.97 (anti-lock) |

**Paradox** is aware and one-way: installs instincts into the swarm; the swarm does not store Paradox.  
Raw episode scars are compressed into **wisdom** (not trauma) before DNA updates.

Deep theory stays out of this README on purpose.

---

## Quick start

```bat
pip install -r REQUIREMENTS.txt
python KERNEL_v1.py --status
python KERNEL_v1.py --demo 40
python nodes\demo_nodes.py
```

Requires: **Python 3.10+**, `numpy`, `matplotlib`.

---

## Wire-in (nodes)

```python
from nodes.ingest import to_interference
from nodes.engine_loop import HealthEngine
from nodes.actuate import plan_actions, apply_shield

eng = HealthEngine(seed=42)
I = to_interference(success_rate=0.55, env_load=1.8)
out = eng.step(I, success_rate=0.55)
plan = out["plan"]   # shield_scale, quarantine_k, revive_k, cool_retries, ...
felt = apply_shield(1.8, plan)
```

See `INTEGRATION.md`.

---

## When to use what

| Need | Use |
|------|-----|
| Who does what (graphs, roles, tools) | LangGraph / CrewAI / etc. |
| Durable jobs that survive crashes | Temporal / SQS / Redis leases |
| Fleet health under storms / thrash | **Paradox Engine** |

They **stack**. This is the health layer, not a replacement for orchestration or durable queues.

---

## What’s in this repo

- `KERNEL_v1.py` — single-file kernel (promoted multi-seed DNA + reflected wisdom)
- `nodes/` — ingest, actuate, HealthEngine
- `portfolio/proof_*` — baseline vs engine demos
- `OPEN_THESE_PROOFS/` — pre-built HTML + charts
- `BUYER_LANGUAGE.md` — how to talk about it without leaking internals

---

## What’s not in this repo (on purpose)

- Training / DNA breeding lab  
- Private ops logs  
- Architecture lectures as the product  

Custom vertical glue → pilot / consulting, not the free core.

---

## Roadmap (public)

- [x] Kernel + proofs + Soft Pack  
- [x] Paradox scar → wisdom path (exam-gated)  
- [ ] Surge / flood **defense** node (absorb thrash, temporary overflow, contract when calm)  
- [ ] Expand-band experiments under extreme I (lab)  
- [ ] Real lease-queue demo beside health layer  

---

## License

See `LICENSE` — personal / demo use friendly.  
Commercial redistribution of the pack as your product: ask first.

---

## Contact / product

- **Gumroad Soft Pack:** https://blakesinger.gumroad.com/l/wcorn  
- Issues / discussion: use this GitHub repo  

Built in public. Feedback welcome — especially multi-agent thrash war stories.
