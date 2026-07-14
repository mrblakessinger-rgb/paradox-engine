# Soft Pack — Quickstart

## 0. See the proofs (0 Python required)

Double-click **`START_HERE.html`**  
or open **`OPEN_THESE_PROOFS/index.html`**

You should see real baseline-vs-engine charts for A, B, and C.

## 1. Install deps (only if re-running)
```bat
pip install -r REQUIREMENTS.txt
```

## 2. Re-run Proof A on your machine
```bat
cd portfolio\proof_a_agent_fleet
python run_proof_a.py
start out\proof_a_case_study.html
```
Expect green Δ ~+0.22

## 3. Re-run B / C
```bat
cd portfolio\proof_b_job_queue
python run_proof_b.py

cd portfolio\proof_c_rate_limit
python run_proof_c.py
```

## 4. Kernel heartbeat
```bat
python KERNEL_v1.py --demo 40
python nodes\demo_nodes.py
```

## 5. Wire your system
Read `INTEGRATION.md` — ingest → HealthEngine → actuate.

## 6. Plugins (easiest)
```bat
python -m plugins.examples.minimal_all
```
See `plugins/README.md` — Fleet / Queue / API / LangGraph / CrewAI drop-ins.
