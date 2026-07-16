# Hallucination as components — not “solve cancer”

**Status:** research doctrine  
**Product today:** Eye of the Storm thrash Soft Pack (separate)  
**Goal:** pick at **systems that fail to work together**, not one magic “no hallucinations” switch.

---

## The end problem is a convergence

People say “the model hallucinated.”  
Usually several layers failed in sequence:

```
retrieval  →  selection  →  generation  →  self-check  →  release  →  retry/thrash
     \___________ any of these can inject or amplify ungrounded claims ___________/
```

We don’t try to “solve hallucinations.”  
We name **aspects**, measure them, and put a **governor** on the junctions.

---

## Aspects (components)

| # | Aspect | What breaks | Why it converges | Our handle (now / later) |
|---|--------|-------------|------------------|---------------------------|
| **A1** | **Knowledge gap** | Model has no fact; still answers | Training cutoff / missing docs | Abstain; don’t invent (release bar) |
| **A2** | **Retrieval miss** | Right doc never fetched | Ranker / chunking / query | Upstream RAG — not our core |
| **A3** | **Retrieval poison** | Wrong / polluted doc looks authoritative | Single-source trust | **Dual evidence + intersection** |
| **A4** | **Source conflict** | Two docs disagree; model picks a side | No multi-source policy | **Intersection / majority policy** |
| **A5** | **Faithfulness gap** | Answer contradicts *its own* sources | Generation ignores context | Claim-level grounding check |
| **A6** | **False confidence** | Sounds sure, is wrong | Training + decoding | **FC only on *released* junk** |
| **A7** | **Self-check theater** | Model “verifies” itself into agreement | Same weights, same bias | Multi-sample + external sources |
| **A8** | **Retry thrash** | Bad answer → more loops → more confident junk | Agent/tool loops | **Thrash-bounded revise + cool** |
| **A9** | **Partial release** | Mix of true + false claims in one answer | No claim strip | **Final strip ungrounded** |
| **A10** | **Metric blind spot** | “Uptime” / fluency scored, not grounded | Wrong scoreboard | MAIN (grounded) / SAFE (grounded∨abstain) |

**Ships as thrash Soft Pack today:** mostly **A8** (and fleet/queue/API cousins of thrash).  
**Logic-loop research:** **A3, A4, A6, A8, A9, A10** in synthetic dual-retrieval exams.  
**Not our lane yet:** full A2 ranker, training A1, world-oracle factuality.

---

## Negative space (what sits between components)

| Between | Gap people miss |
|---------|-----------------|
| Retrieval **and** generation | Doc is right; model still invents (A5) |
| Generation **and** release | Check ran, bad claim still shipped (A9) |
| Self-check **and** thrash | Unlimited “think harder” (A7+A8) |
| Confidence **and** ground truth | High conf ≠ supported (A6) |
| Source A **and** source B | Union treated as truth (A3+A4) |
| Product metrics **and** honesty | Fluency scored as success (A10) |

**Negative space product:** a **governor at the junctions** — not another end-to-end “truth model.”

```
multi-retrieval  →  intersection ground  →  thrash-capped revise
        →  strip ungrounded  →  release OR abstain
        →  FC only if we released junk
```

Same DNA as Eye of the Storm: **cool the stampede, dual scoreboard, don’t ship false calm.**

---

## How many pieces?

Rough map for *answer* reliability (not all of AI):

| Layer | Pieces (examples) |
|-------|-------------------|
| Data / index | chunking, embeddings, filters |
| Retrieve | top-k, re-rank, multi-query |
| Ground | multi-source policy, citations |
| Generate | decoding, tools, CoT |
| Verify | NLI, self-consistency, second model |
| Control | thrash budget, abstain, cool |
| Observe | MAIN/SAFE/FC metrics, exams |

We own **control + observe + a slice of ground/verify** first.  
We **partner or leave alone** retrieve/train/edge.

---

## What we will not claim

- “Hallucinations eliminated”  
- Beating foundation labs on base factuality  
- Single-doc RAG is safe if the model is “smart enough”  
- Unlimited logic loops as a fix (that *is* thrash)

---

## Link to code (lab / research)

| Doctrine | Module |
|----------|--------|
| Dual evidence, strip, FC, thrash budget | `logic_loop_governor` (research) |
| Aspects status | this file |
| Product thrash | Soft Pack proofs A/B/C |

Re-run research exams from the private lab when present; public repo keeps this map honest and short.
