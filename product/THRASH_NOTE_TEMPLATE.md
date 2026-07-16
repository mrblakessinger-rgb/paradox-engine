# Free thrash note — template (hard cap)

**Purpose:** Real-world feedback without free consulting forever.  
**Cap:** **3–5 hours** wall-clock total (read + write). Stop when the cap hits.  
**Offer:** One-page findings. No rebuild. No obligation. Product link only if they ask.

---

## 1) What they send you (paste this to them)

```
FREE THRASH NOTE (3–5h hard cap · no obligation)

Reply with as much as you have — bullets are fine:

1) What system? (agents / workers / API clients / other)
2) What’s thrashing? (retries, tool flakes, 429s, queue pileup, …)
3) Rough numbers if you have them:
   - success % or goodput
   - retry rate / 429 rate
   - how often it blows up (daily / weekly / launch only)
4) What you’ve already tried (timeouts, rate limits, more machines, …)
5) Optional: one short “bad day” story (5–10 lines)

I’ll send a one-page note:
  • what’s thrashing (plain language)
  • 2–3 levers to try
  • whether Eye of the Storm proofs are even relevant

No pitch deck. No sales call required.
```

---

## 2) Your internal checklist (before you write)

- [ ] Read once; don’t redesign their whole stack  
- [ ] Name **one** primary thrash pattern  
- [ ] Cap at **3 levers** (not 12)  
- [ ] Map to A / B / C proof only if honest  
- [ ] No DNA / hive / Paradox theory  
- [ ] Time box: if past 5h, ship what you have  

---

## 3) One-page reply template (you fill this)

```markdown
# Thrash note — [their name / handle]
**Date:**  
**Cap used:** ~_ h (of 3–5)  
**System (as described):** agents / queue / API / other  

## What’s thrashing
[2–4 sentences. Name the pattern: tool-flake cascade / retry stampede / 429 self-DDoS / backlog death spiral.]

## Evidence I used
- [what they reported: rates, story, gaps]

## 2–3 levers (try in order)
1. **[Lever]** — why · how to try in 1 day  
2. **[Lever]** — why · how to try in 1 day  
3. **[Lever]** — optional / only if 1–2 help  

## What not to do (optional)
- [e.g. “more retries without a cool-down will feed the thrash”]

## Proofs (only if relevant)
| Your shape | Closest free proof | Lift (re-runnable) |
|------------|--------------------|--------------------|
| tool flakes / agents | A agent fleet | +0.22 success |
| worker retry storms | B job queue | +0.23 success |
| 429 / shared budget | C API thrash | +0.24 goodput |

Free re-run: https://github.com/mrblakessinger-rgb/paradox-engine  
Pack (only if you want it): https://blakesinger.gumroad.com/l/wcorn  

## Out of scope for this note
Wire-in, custom code, and multi-day redesign are separate paid thrash work — not this free note.

— Blake · Paradox Engine — Eye of the Storm
```

---

## 4) Paid thrash work (if they ask)

| Scope | Ballpark | Includes |
|-------|----------|----------|
| Fixed thrash review | $150–250 | deeper read + written plan |
| Wire-in assist | $250–400 | Soft Pack / plugins against their metrics |
| Pilot | custom | residual / production path |

Eye of the Storm zip is **optional** if they already own it.

---

## 5) Cap discipline (non-negotiable)

| Signal | Action |
|--------|--------|
| Hit 5 hours | Ship incomplete note; say “cap hit” |
| They want a full redesign | Point to paid scope |
| Silence after offer | Fine — no chase spam |
| Great fit + they buy | Great — still no free forever |

**Reputation tool, not free consulting forever.**
