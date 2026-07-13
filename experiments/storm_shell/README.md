# Storm shell experiments (prototype)

Defense-stack lab on top of the **promoted** Paradox kernel.  
**Not** Soft Pack DNA promote. **Not** a second product.

## What’s here

| Script | What |
|--------|------|
| `expand_l2_demo.py` | Mid-band (L2) flex + soft edge absorb |
| `hell_beacons_surge_demo.py` | Beacons + surge shield · multi-scenario hell matrix |
| `storm_surge_learn_cycles.py` | Storm surge **shell v2** + 3-cycle Paradox learn |
| `toughen_then_hell_eval.py` | Train **3.0↔6.4** ramps ×3, then re-run hell suite |
| `_annihilation_pass.py` | Cliff finder (I~7 / double-nuke) |

Results from the last local run are under `out/` (JSON + PNG).

## Headline results (honest)

- **Storm surge shell** is the main lever under hell / flicker / beyond_map (~**+0.07** late vs baseline).
- **Beacons** help edge; stack with shell.
- **3-cycle learn** and **3.0↔6.4 toughen** move instincts a little; little extra once shell is already on.
- **Annihilation** (I~7+) still hard-breaks — shell delays death, not immortality.

## Run (from repo root)

```bat
pip install -r REQUIREMENTS.txt
cd experiments\storm_shell
python hell_beacons_surge_demo.py
python storm_surge_learn_cycles.py
python toughen_then_hell_eval.py
python expand_l2_demo.py
```

Requires: Python 3.10+, `numpy`, `matplotlib`. Scripts auto-find `KERNEL_v1.py` at repo root.

## Product note

Primary buyer path stays Proofs A/B/C + Soft Pack.  
This folder is **storm-mode R&D** — optional future actuate skin, not a second Gumroad SKU.
