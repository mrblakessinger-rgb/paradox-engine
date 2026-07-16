# Logic-loop governor — doctrine (inspiration capture)

**Status:** STARTED 2026-07-15  
**Lane:** strengths cousin of Eye of the Storm — **not** front door, not model training  
**Loop:** always `ops/LEARNING_LOOP.md` (predict → act → note → compare → learn → exam)

---

## One line

> Govern **verify / revise / abstain** under a **thrash budget** so reasoning loops reduce ungrounded claims instead of amplifying confident nonsense.

---

## Problem (two faces)

| Face | Meaning | Our handle |
|------|---------|------------|
| **Bad logic loop** | Runaway CoT / retry thrash that burns tokens and doubles down on wrong claims | **Thrash cool** (home turf) |
| **Good logic loop** | Draft → verify claims → revise or abstain | **Controlled verification** |

Research cousins: Chain-of-Verification, self-consistency, review–fix.  
We do **not** train foundation models. We **govern the loop** around any model/agent.

---

## Non-goals (v1)

- Beat OpenAI/Anthropic on base factuality  
- Full RAG platform / vector DB product  
- Promise “zero hallucinations”  
- Replace Soft Pack thrash as Gumroad front door  

---

## Goals (v1)

1. **Faithfulness first** — claims must not contradict *provided sources* (easier ground truth than world knowledge).  
2. **False confidence bar** — high confidence + check fail = cool / don’t release as fact.  
3. **Thrash budget** — hard cap on revise loops; prefer abstain over infinite think.  
4. **Dual scoreboard** (same DNA as 4B/4A):  
   - **MAIN (grounded):** released claims that are source-supported  
   - **SAFE:** grounded **or** honest abstain (not wrong)  
5. **Exam ladder** — baseline one-shot vs governor; multi-seed; grow difficulty later.  
6. **Baseline vs engine charts** — Soft Pack style proof.

---

## Always-on spine

```text
1 PREDICT   risk: thrash, prior disagree rate, claim density, source disagreement
2 ACT       draft | revise | cool (skip extra samples) | abstain
3 VERIFY    self-consistency (multi-sample vote) + multi-source grounding
4 NOTE      claims released, abstained, loops used, conf
5 COMPARE   vs ground truth (exam) + vs prediction
6 LEARN     exam-gated knobs (max_loops, conf_threshold, cool, source_policy)
7 WISDOM    rules: when to abstain, when to revise once
```

### Multi-source grounding (poison / conflict) — 2026-07-16

| Policy | Meaning |
|--------|---------|
| **all** | Claim must appear in *every* retrieval (default when ≥2 sources) |
| **majority** | Claim in ≥ `min_source_frac` of sources |
| **any** | Claim in ≥1 source (legacy single-doc) |

**Poison fix:** dual independent retrievals with *different* pollution → intersection ≈ truth.  
**Conflict fix:** two docs → release only intersection; exclusive sides stripped.  
**Never** trust a single polluted `model.belief` source alone for industrial faithfulness.

---

## Metrics (buyer + research)

| Metric | Definition | Better |
|--------|------------|--------|
| **support_rate** | supported released / released claims | ↑ |
| **false_claim_rate** | unsupported released / released | ↓ |
| **false_confidence_rate** | high conf ∧ unsupported (or released wrong) | ↓ |
| **abstain_rate** | refused or hedged / total items | context |
| **loop_steps** | verify/revise iterations used | ↓ under thrash budget |
| **MAIN** | of non-abstain releases, fraction supported | ↑ primary |
| **SAFE** | of all items, fraction (supported release ∨ abstain) | ↑ secondary |

**Primary pass (v1):** MAIN high + false_confidence low + loop_steps ≤ budget.  
**Secondary:** SAFE high (abstain allowed).

---

## Strengths map

| Soft Pack / DefenseStack | Logic-loop governor |
|--------------------------|---------------------|
| Cool thrash | Cap revise / sample thrash |
| false_pre_arm | false_confidence |
| MAIN / SAFE | grounded / grounded∨abstain |
| Horizon pre-arm | predict disagree risk before extra loops |
| Adaptive exams | harder claim sets until plateau |

---

## Code map

| Piece | Path |
|-------|------|
| Governor | `nodes/logic_loop_governor.py` |
| Exam | `real_world/logic_loop_exam.py` |
| Out | `real_world/out/logic_loop_*` |

---

## Build order

- [x] Doctrine (this file)  
- [x] Thin governor + synthetic faithfulness world (`nodes/logic_loop_governor.py`)  
- [x] Baseline vs governor exam + chart (`real_world/logic_loop_exam.py`)  
- [ ] Harder exams: multi-hop claims, higher noise, label noise on sources  
- [ ] Later: real LLM adapter (optional), RAG faithfulness only  
- [ ] Later: thrash Soft Pack plugin surface  

### First freeze (2026-07-15)

| Arm | MAIN | SAFE | false conf | support |
|-----|-----:|-----:|-----------:|--------:|
| baseline one-shot | ~0.01 | ~0.01 | ~0.86 | ~0.33 |
| **governor** | **~0.99** | **1.00** | **0.00** | **1.00** |

Lift MAIN ≈ **+0.98** (strict MAIN = *all* released claims source-supported; baseline dumps mixed drafts).  
Re-run: `python real_world/logic_loop_exam.py`

### Adversarial freeze (2026-07-16) — poison/conflict fix

Multi-source grounding (`source_policy=all` on dual retrievals):

| Mode | gov MAIN | gov SAFE | FC | lift MAIN |
|------|--------:|---------:|---:|----------:|
| poison (was 0/0) | **~0.46** | **1.00** | **0** | **+0.46** |
| conflict (was 0/0) | **~0.56** | **1.00** | **0** | **+0.56** |
| multi_hop | ~1.00 | 1.00 | 0 | +1.00 |
| stampede | ~0.96 | 1.00 | 0 | +0.96 |

**Overall PASS.** Product lesson: dual independent retrieval + intersection beats trusting one polluted doc.  
Re-run: `python real_world/logic_loop_adversarial_exam.py`

### Peak harden (2026-07-16) — doctrine at best

| Mechanism | Behavior |
|-----------|----------|
| Source fight | risk↑, agree_need↑ scaled by disagreement, extra thrash cool, block partial release |
| Empty intersection | immediate abstain (SAFE, FC=0) |
| Revise path | drafts biased to **intersection pool**, not belief-union |
| Final strip | ungrounded never released |
| FC | only if released high-conf ungrounded; abstain ≠ FC |
| Thrash budget | loops ≤ max_loops |

**Doctrine micro-exam:** `python real_world/logic_loop_doctrine_exam.py` → **5/5 PASS**  
**Adversarial after peak:** poison/conflict/multi_hop/stampede **MAIN=1.0 SAFE=1.0 FC=0** (synthetic dual-retrieval world)

---

## Front door reminder

**Sell thrash Soft Pack first.** This is the long research cousin. Same DNA; different world.
