# Research modules (not the paid Soft Pack)

| Doc / code | Role |
|------------|------|
| `HALLUCINATION_ASPECTS.md` | Component map — pick junctions, not “solve hallucinations” |
| `LOGIC_LOOP.md` | Status of answer-governor research |
| `LOGIC_LOOP_GOVERNOR.md` | Full doctrine |
| `logic_loop_governor.py` | Governor implementation (offline) |
| `logic_loop_*_exam.py` | Synthetic exams |

## Run exams (from repo root)

```bat
set PYTHONPATH=experiments\research
python experiments\research\logic_loop_doctrine_exam.py
python experiments\research\logic_loop_adversarial_exam.py
python experiments\research\logic_loop_exam.py
```

Requires `numpy`, `matplotlib`. Outputs under `experiments/research/out/` if paths resolve; some scripts write to `real_world/out` — patch or create that folder under research if needed.

**Product buyers:** ignore this folder. Use Soft Pack proofs A/B/C and Gumroad.
