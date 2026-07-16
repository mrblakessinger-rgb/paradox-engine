# Logic-loop governor — research module (not paid zip)

**Status:** offline research · **not** Eye of the Storm v1 product  
**Doctrine:** multi-source ground · thrash-bounded revise · strip ungrounded · FC only on released junk  
**Aspects targeted:** A3 poison retrieval · A4 conflict · A6 false confidence · A8 thrash · A9 strip · A10 dual scoreboard  

See [`HALLUCINATION_ASPECTS.md`](HALLUCINATION_ASPECTS.md).

---

## What it is

A **control loop around answers**, same family as thrash Soft Pack:

```
predict risk (incl. source disagreement)
  → draft / revise under thrash budget
  → verify (self-consistency + multi-source policy)
  → strip ungrounded
  → release grounded OR abstain
  → FC only if we released high-conf junk
```

**Not:** training a foundation model. **Not:** “hallucinations solved.”

---

## Peak mechanisms (locked in lab)

| Mechanism | Behavior |
|-----------|----------|
| Source disagreement | risk↑, stricter agree, extra cool, block partial release |
| Empty intersection | immediate abstain (SAFE, FC=0) |
| Dual evidence | revise toward **intersection**, not belief-union |
| Final strip | ungrounded never released |
| FC | abstain after junk ≠ false confidence |
| Thrash budget | loops ≤ max_loops |

Lab exams (private tree when present): doctrine 5/5, adversarial poison/conflict PASS, base faithfulness PASS.

---

## Product path (later)

1. Thin multi-chunk / multi-doc adapter (real retrieval → `sources=`)  
2. Claim split on real text  
3. Soft Pack–style baseline vs governor chart on a small public faithfulness set  
4. Optional paid module — **after** thrash Soft Pack has real users  

**Until then:** thrash Soft Pack is the storefront. This file is honesty about the research cousin.

---

## Suite placement

```
Eye of the Storm (ships)     — fleet / queue / API thrash
Logic-loop (research)        — answer grounding under multi-source thrash
Residual DefenseStack (lab)  — origin residual behind edge (not storefront)
```

Complement LangGraph, Temporal, Cloudflare — fill **junction** failures, don’t replace their cores.
