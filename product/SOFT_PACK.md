# Soft Pack — offer draft (Month 2 money surface)

**Price band:** $99 – $199  
**Recommended launch price:** **$149**  
**Name (working):** Infinity Engine Soft Pack  
**Buyer promise (performance only):** Drop-in health control for flaky multi-agent / worker systems — with measured lifts you can re-run.

---

## What they get

| Item | Why it sells |
|------|----------------|
| `KERNEL_v1.py` (frozen) | The engine binary they run |
| `nodes/ingest.py` + `nodes/actuate.py` | Clean wire-in points (no need to touch secrets) |
| Proof A runner + HTML recipe | “Show me it works” in one command |
| ONE_PAGER + BUYER_LANGUAGE card | How to talk about it without leaking internals |
| 1-page Integration README | Inputs/outputs only |

## What they do **not** get (protect the moat)

- Training / evolution / exam harness  
- Full DNA lab history or “how to re-breed”  
- Deep Paradox / hive theory docs  
- Consulting hours (that’s the $1.5k pilot later)  
- Source walkthrough of every internal lever  

If they need custom vertical glue → **pilot**, not Soft Pack.

---

## Who it’s for (one sentence each)

1. **Builder with agent fleets** that die under tool storms  
2. **Someone running worker queues** with retry stampedes  
3. **Hobby/pro Python dev** who wants a health layer, not a lecture  

## Who it’s not for

- People who want “AI that writes novels”  
- People who demand white-box neural explanations before numbers  
- Free-only tire-kickers (send them the public one-pager later)

---

## Checkout copy (paste-ready)

> **Infinity Engine Soft Pack — $149**  
> Health controller for multi-agent and worker systems under load storms.  
> **Measured:** +22 pts fleet success · +23 pts job queue · +24 pts API goodput (re-runnable demos included).  
> You get the frozen kernel, ingest/actuate wire-in, and Proof A pack. Internals stay sealed — you buy the lift.

---

## Delivery checklist (when first sale happens)

- [x] Zip dry-run: `product/dist/InfinityEngine_SoftPack_v1.zip`  
- [x] Stage folder: `product/dist/InfinityEngine_SoftPack_v1/`  
- [x] Rebuild: `python product/build_soft_pack.py --zip`  
- [x] Verified: Proof A from staged tree → **+0.220**  
- [x] Pay link **notes**: `product/PAY_LINK.md`  
- [x] Pay link **live**: https://blakesinger.gumroad.com/l/wcorn  
- [x] Landings + ad skins Buy buttons wired  
- [ ] 24h support: email for install only, not architecture tours  

### Dry-run layout (buyer zip)

```
InfinityEngine_SoftPack_v1/
  KERNEL_v1.py
  nodes/                  # ingest, actuate, engine_loop, demo
  portfolio/
    proof_a_agent_fleet/  # hero +0.22
    proof_b_job_queue/    # +0.23
    proof_c_rate_limit/   # +0.24
    ONE_PAGER.html
  README.md · QUICKSTART.md · INTEGRATION.md
  BUYER_LANGUAGE.md · LICENSE_PERSONAL.txt · REQUIREMENTS.txt
```

**Not in zip:** `ops/`, `product/ads/`, training lab, your daily logs.

---

## Price decision

| Price | When |
|-------|------|
| $99 | First 5 buyers / friends / “I need a W” |
| **$149** | **Default public** |
| $199 | After 90s video + 3 public proof screenshots live |

**Decision now:** default **$149**. Change only with evidence.

## Ad skins (one pack, three doors)

| Skin | File | Hook metric |
|------|------|-------------|
| Agent fleets | `ads/ad_fleet.html` | +0.22 success |
| Job queues | `ads/ad_queue.html` | +0.23 success |
| API thrash | `ads/ad_api.html` | +0.24 goodput |
| Hub | `ads/index.html` | all three |
| Post copy | `ads/POST_OPENERS.md` | paste-ready |

**Rule:** skins only change the camera. Price, zip, and kernel stay one.

## Status
**DRAFT READY** — not sold yet. Wire pay link when you want money live. Ad skins live.
