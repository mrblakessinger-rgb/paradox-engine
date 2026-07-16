# Soft Pack thrash — easy-sell front door

**Product:** Paradox Engine — Eye of the Storm  
**Gumroad:** https://blakesinger.gumroad.com/l/wcorn  
**Price:** $149 (see `SOFT_PACK.md`)  
**Job:** First invoice path — **thrash / self-DDoS / 429**, not residual DDoS.

---

## One sentence (use this)

> When agents, workers, or API clients thrash under load, Eye of the Storm keeps real work alive and cools the stampede — measured, re-runnable.

---

## Who buys this (easy)

| Buyer | Pain they already have | Your door |
|-------|------------------------|-----------|
| AI / agent builders | Tool flakes → fleet dies mid-run | Proof A **+0.22** |
| Backend / queue owners | Retry storms melt workers | Proof B **+0.23** |
| API / client teams | 429 loops kill goodput | Proof C **+0.24** |

**Not first door:** “We absorb Tbps” · “Replace Cloudflare” · DNA/hive lectures.

---

## Proof numbers (re-run 2026-07-14)

| Proof | World | Baseline → Engine | Lift |
|-------|-------|-------------------|------|
| **A** | Agent fleet | 0.474 → 0.695 success | **+0.221** |
| **B** | Job queue | 0.510 → 0.743 success | **+0.232** |
| **C** | API thrash | 0.018 → 0.257 goodput | **+0.239** |

Public shorthand: **+0.22 / +0.23 / +0.24**  
Re-run: `python product/run_thrash_show.py`

---

## 60-second pitch (verbatim)

1. “Not another agent framework — a **health layer** when load storms hit.”  
2. “Three proofs you re-run: fleets, queues, API thrash.”  
3. “Baseline vs engine — about **+22 / +23 / +24** points.”  
4. “Wire metrics in, actuate cool-retries / shield / quarantine — frozen kernel.”  
5. “$149 one-time Soft Pack. Free proofs on GitHub first.”

---

## Gumroad thrash block (paste under description or as update)

```
THRASH FRONT DOOR (what this actually fixes)

• Agents die when tools flake → Proof A +0.22 success
• Worker pools thrash on retries → Proof B +0.23 success  
• API clients stampede a shared budget → Proof C +0.24 goodput

Eye of the Storm = health governor under load storms.
Not LangGraph. Not Temporal. Not Cloudflare.
Re-run the demos; buy the frozen kernel when you want the calm in your stack.

Free proofs: GitHub paradox-engine
Pack: $149 · personal license
```

---

## Post openers (thrash-first)

**Universal:**
> Your fleet doesn’t need another framework. It needs a health governor when retries and 429s stampede.  
> +0.22 fleets · +0.23 queues · +0.24 API goodput — re-runnable. Eye of the Storm.

**Agents:**
> Multi-agent runs look fine until tools flake. Baseline 0.47 → 0.69 with a health controller. Same engine for queues and API thrash.

**API:**
> Shared budget + 429 storms: naive clients thrash themselves to death. Goodput 0.02 → 0.25. Eye of the Storm.

Full set: `ads/POST_OPENERS.md`

---

## 90s demo (thrash path)

1. Open `portfolio/ONE_PAGER.html` — pitch  
2. Open Proof **C** chart (API thrash — clearest “stampede” story)  
3. Flash Proof A or B table  
4. CTA: free GitHub proofs → $149 pack  

Script detail: `portfolio/DEMO_90S.md` (thrash section)

---

## Paste-ready + free thrash note (use these)

| File | Use |
|------|-----|
| `THRASH_DOOR_PASTE.md` | Posts, Gumroad add-on, DM invite, thank-you |
| `THRASH_NOTE_TEMPLATE.md` | Free 3–5h note — what they send + your one-pager |

## What to do this week (momentum, not spam)

| Action | Why |
|--------|-----|
| Re-run thrash show once | Fresh confidence + screenshots |
| One post from `THRASH_DOOR_PASTE.md` (one realm) | Consistent door |
| Offer free thrash note (cap hard) | Real feedback without free consulting forever |
| Don’t wait for residual DDoS SKU | Industrial stack is depth; thrash is invoice |

---

## Honest status

- Product is **live** — no sales yet is normal early.  
- Feedback comes from: free thrash notes, GitHub, one clear demo, persistence.  
- Keep building; package boring; lead with numbers.

**Stack under the hood** (lab): DefenseStack residual work continues as *credibility depth*, not the Gumroad headline.

---

## Commands

```bat
cd "...\INFINITY ENGINE KERNAL 1"
python product/run_thrash_show.py
python portfolio/proof_a_agent_fleet/run_proof_a.py
python portfolio/proof_b_job_queue/run_proof_b.py
python portfolio/proof_c_rate_limit/run_proof_c.py
python product/build_soft_pack.py --zip
```
