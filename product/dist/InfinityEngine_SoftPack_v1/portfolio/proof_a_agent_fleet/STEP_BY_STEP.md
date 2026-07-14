# Proof A — Step by step (freshie guide)

## What you’re proving

**Real-world-shaped problem:** A fleet of AI/tool agents call flaky APIs.  
Storms and jumps make tools fail more. Agents can cascade-crash.

**Your product:** Infinity Engine (`KERNEL_v1`) acts as a **health controller**:

1. **Ingest** — turn failures into interference `I`  
2. **Kernel** — swarm hive holds ~0.92 health  
3. **Actuate** — quarantine worst agents / revive when healthy  

**Compare:** Baseline (no engine) vs With Engine.

---

## Before you start (one-time setup)

### Step 0 — Tools you need
1. **Python** installed (3.10 or newer).  
   Check: open Command Prompt and type:
   ```bat
   python --version
   ```
2. **numpy** and **matplotlib**:
   ```bat
   pip install numpy matplotlib
   ```

### Step 1 — Know your folder
Everything lives here:

```
Desktop\INFINITY ENGINE KERNAL 1\
  KERNEL_v1.py                          ← the brain
  portfolio\proof_a_agent_fleet\        ← this proof
    run_proof_a.bat
    run_proof_a.py
    agent_fleet.py
    STEP_BY_STEP.md                     ← you are here
    out\                                ← results appear here
```

---

## Run Proof A (easiest way)

### Step 2 — Double-click
1. Open File Explorer.  
2. Go to `INFINITY ENGINE KERNAL 1\portfolio\proof_a_agent_fleet\`  
3. Double-click **`run_proof_a.bat`**  
4. Wait for it to finish (about 10–30 seconds).  
5. A browser window / image should open with results.

### Step 2 (alternate) — Command Prompt
```bat
cd "C:\Users\mrbla\OneDrive - Butte-Glenn Community College District\Desktop\INFINITY ENGINE KERNAL 1\portfolio\proof_a_agent_fleet"
python run_proof_a.py
```

---

## Step 3 — Read the results

Open:

```
portfolio\proof_a_agent_fleet\out\proof_a_case_study.html
```

You should see:

| Number | Meaning |
|--------|---------|
| Baseline mean success | Fleet alone (usually worse) |
| Engine mean success | Fleet + Infinity Engine |
| Δ (delta) | Improvement |
| Kernel late stability | Should sit near **0.92** |
| Plot | Pink = baseline, green = with engine |

**Good outcome:** Engine mean/late/p10 **higher** than baseline; kernel not stuck at 1.0.

---

## Step 4 — What to do with this (portfolio)

1. Keep the `out\` folder (proof artifact).  
2. In `ops\DAILY_LOG.md`, write: “Ran Proof A — engine improved success by X.”  
3. Later: screenshot the HTML for a demo video.

---

## Step 5 — If something breaks

| Error | Fix |
|-------|-----|
| `python` not found | Install Python, check “Add to PATH” |
| `No module named numpy` | `pip install numpy matplotlib` |
| `Could not import KERNEL_v1` | Confirm `KERNEL_v1.py` is in `INFINITY ENGINE KERNAL 1\` (parent of `portfolio`) |
| Window closes too fast | Always use `run_proof_a.bat` (it pauses) |

---

## What’s inside (optional learning)

| File | Role |
|------|------|
| `agent_fleet.py` | Fake multi-agent world (flaky tools) |
| `run_proof_a.py` | Baseline vs engine experiment |
| `KERNEL_v1.py` | Your promoted kernel (not edited for this proof) |

You are **not** rewriting the kernel. You are **proving** it on an open-source-shaped problem.

---

## You’re done with Proof A when

- [ ] `run_proof_a.bat` finishes without error  
- [ ] You opened `out\proof_a_case_study.html`  
- [ ] You can say out loud: “Baseline vs engine — engine holds the fleet up under storms.”  

**Next (later):** Proof B (job queue) or polish this into a 90-second video.

---

## Check-in phrase for Grok

After you run it, message:

> **check-in — Proof A done**  
> (paste the mean success numbers if you want feedback)
