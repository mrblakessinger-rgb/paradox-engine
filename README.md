# Paradox Engine — Eye of the Storm

**Chaos can hit it. Chaos can’t own it.**  
**Not unbreakable — but your system won’t break it.**

Self-stabilizing **health layer** for multi-agent fleets, worker queues, and API clients under load storms.

Not a chatbot. Not another agent framework.  
A **fleet health controller** — holds a target band under thrash without locking at fake “perfect 1.0” and going blind.

**Product (zip + support):** [Eye of the Storm — $149 on Gumroad](https://blakesinger.gumroad.com/l/wcorn)

---

## Problems it actually measures against

| | Pain | Proof | Result |
|---|------|-------|--------|
| **X** | Agent fleets die when tools flake | **A** — fleet / tool storms | **0.474 → 0.695** success (**+0.221**) · final active **9 → 20** |
| **Y** | Worker queues stampede on retries | **B** — job queue storms | **0.510 → 0.743** success (**+0.232**) |
| **Z** | API clients melt under 429 thrash | **C** — rate-limit thrash | **0.018 → 0.257** goodput (**+0.239**) · late alive **0 → ~8** |

Kernel late stability under those runs: **~0.94–0.95** (target band ~0.92 — holds without freezing at 1.0).

Same pattern across **three** different worlds. Seeded. **You re-run it.**

Public shorthand: **+0.22 / +0.23 / +0.24**.

---

## See proofs in 10 seconds

1. Open [`START_HERE.html`](START_HERE.html)  
2. Or browse [`OPEN_THESE_PROOFS/`](OPEN_THESE_PROOFS/)

Re-run:

```bat
pip install -r REQUIREMENTS.txt
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
start out\proof_a_case_study.html
```

Same pattern for `proof_b_job_queue` and `proof_c_rate_limit`.

---

## One-sentence pitch

> Eye of the Storm keeps multi-agent and multi-worker systems near a target health band under random load spikes — without constant babysitting.

---

## Architecture (surface only)

```
your metrics  →  ingest  →  KERNEL  →  actuate  →  your system
```

| Piece | Role |
|-------|------|
| **Ingest** | Failures / load → interference |
| **Kernel** | Swarm health step (frozen contract) |
| **Actuate** | Shield, cool thrash, quarantine worst, revive when healthy |
| **Contract** | Target ~0.92 · soft ceiling ~0.97 (anti-lock) |

Internals stay sealed. Buyers buy **performance**, not a theory seminar.

---

## Quick start

```bat
pip install -r REQUIREMENTS.txt
python KERNEL_v1.py --status
python KERNEL_v1.py --demo 40
python nodes\demo_nodes.py
```

Requires: **Python 3.10+**, `numpy`, `matplotlib`.

Wire-in: [`INTEGRATION.md`](INTEGRATION.md) · Buyer language: [`BUYER_LANGUAGE.md`](BUYER_LANGUAGE.md)

---

## When to use what

| Need | Use |
|------|-----|
| Who does what (graphs, roles, tools) | LangGraph / CrewAI / etc. |
| Durable jobs that survive crashes | Temporal / SQS / Redis leases |
| Fleet health under storms / thrash | **Paradox Engine — Eye of the Storm** |

Use them to run work. Use **Eye of the Storm** when fleets thrash under load.

---

## Product vs this repo

| | GitHub (this) | Gumroad pack |
|--|---------------|--------------|
| Proofs A/B/C | Yes | Yes |
| Kernel + ingest/actuate | Yes | Yes + buyer packaging |
| Support | Issues / community | Personal license support |
| Trading / lab mesh | **Not the product** | Not in the zip |

---

## License

See `LICENSE`. Product sales and personal license terms are on Gumroad.
