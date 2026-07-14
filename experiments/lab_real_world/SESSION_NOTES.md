# Real-world session — HTTP fleet

**Date:** 2026-07-12  
**Demo:** `http_fleet_demo.py` → real HTTP to httpbin.org  

## What you just saw

Soft Pack **nodes** (ingest → HealthEngine → actuate) on workers that leave the machine and hit the public internet, with a shared API-style budget.

| Metric | Baseline | Engine | Δ |
|--------|----------|--------|---|
| Mean success | 0.387 | **0.815** | **+0.428** |
| Late success | 0.350 | **0.606** | **+0.256** |
| Workers alive end | 6 | **8** | +2 |
| Wall time | 27.4s | **10.3s** | faster (less thrash) |

**Open:** `real_world/out/http_fleet_case_study.html`

## Why this counts as “real”

- Real TCP/HTTP (not only numpy dice)  
- Shared quota thrash (budget + 429/500 paths)  
- Same wire-in surface as Soft Pack buyers (`nodes/`)  
- You can re-run anytime (needs internet)

## What this is *not* yet

- Not a customer production system  
- Not a merged OSS PR  
- Not LangGraph/Temporal integration  

Those are the next exposure steps.

## Your next 30–60 min (pick one)

### A — Re-run yourself (ownership)
```bat
cd "…\INFINITY ENGINE KERNAL 1"
python real_world\http_fleet_demo.py
start real_world\out\http_fleet_case_study.html
```

### B — Realm exposure (people)
1. Open: https://github.com/search?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22+retry+OR+timeout+language%3APython&type=issues  
2. Pick **one** issue you understand  
3. Comment with a short plan (template in `ops/FREE_PORTFOLIO_PRS.md`)  
4. Log issue URL in `ops/DAILY_LOG.md`

### C — Visibility
Post LocalLLaMA with this chart + Soft Pack link (optional same day).

## Doctrine reminder

Show **numbers**. Don’t open DNA in public threads.
