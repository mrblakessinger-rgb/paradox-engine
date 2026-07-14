"""
Multi-seed exam gate — promote reflected DNA only if it PASSES
==============================================================
Compares KERNEL PROMOTED_DNA vs KERNEL_v1_dna_reflected.json across
hostile schedules. Writes PROMOTE or HOLD verdict.

  python real_world/exam_reflected_dna.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
REFLECTED = ROOT / "KERNEL_v1_dna_reflected.json"

SEEDS = [3, 7, 11, 21, 42, 77, 99, 123]
STEPS = 100

# Gate criteria (must beat or match promoted within tolerance)
MIN_LATE = 0.90
MAX_LOCK = 0.05
MAX_LATE_DROP_VS_PROMOTED = 0.008  # reflected may not lag promoted by more than this


def load_reflected() -> dict:
    if not REFLECTED.exists():
        raise FileNotFoundError(f"Run paradox_reflect first: missing {REFLECTED}")
    return json.loads(REFLECTED.read_text(encoding="utf-8"))


def run_kernel(dna: dict, seed: int, steps: int = STEPS) -> dict:
    rng = np.random.default_rng(seed)
    agents = K.make_swarm(rng)
    paradox = K.Paradox(dna)
    paradox.load_dna(dna)
    # Keep kernel contract target (anti-trauma hijack)
    paradox.intuition["target_coherence"] = K.TARGET_STABILITY
    paradox.install_drivers(agents)
    ambient = 0.0
    I = 1.7
    series = []
    for t in range(steps):
        if rng.random() < 0.12:
            I = float(rng.choice([0.7, 1.2, 1.8, 2.4, 2.9, 3.0]))
        else:
            I = float(np.clip(I + rng.normal(0, 0.09), 0.5, 3.0))
        for a in agents:
            a.step(I, ambient, rng)
        ambient = 0.03 * float(np.mean([a.flux for a in agents]))
        paradox.hive_pair_churn(agents, rng)
        paradox.install_drivers(agents)
        for a in agents:
            tc = a.instinct.get("target_coherence", K.TARGET_STABILITY)
            a.performance = float(
                np.clip(1.0 - 1.2 * abs(a.coherence - tc) - 0.4 * a.pred_error, 0, 1)
            )
        stab = K.stability(agents)
        series.append(stab)
    arr = np.array(series, float)
    late_n = max(1, steps // 5)
    return {
        "mean": float(np.mean(arr)),
        "late": float(np.mean(arr[-late_n:])),
        "min": float(np.min(arr)),
        "locked_frac": float(np.mean(arr >= K.CEILING_SOFT)),
    }


def main() -> int:
    print("=" * 64)
    print(" EXAM GATE — reflected DNA vs promoted")
    print("=" * 64)
    reflected = load_reflected()
    promoted = K.PROMOTED_DNA

    rows = []
    for seed in SEEDS:
        p = run_kernel(promoted, seed)
        r = run_kernel(reflected, seed)
        rows.append({"seed": seed, "promoted": p, "reflected": r})
        print(
            f"  seed={seed:3d}  promoted late={p['late']:.4f} lock={p['locked_frac']:.3f}  "
            f"reflected late={r['late']:.4f} lock={r['locked_frac']:.3f}  "
            f"Δlate={r['late']-p['late']:+.4f}"
        )

    p_late = float(np.mean([x["promoted"]["late"] for x in rows]))
    r_late = float(np.mean([x["reflected"]["late"] for x in rows]))
    p_lock = float(np.mean([x["promoted"]["locked_frac"] for x in rows]))
    r_lock = float(np.mean([x["reflected"]["locked_frac"] for x in rows]))
    r_min = float(np.min([x["reflected"]["min"] for x in rows]))

    checks = {
        "reflected_late_ge_min": r_late >= MIN_LATE,
        "reflected_lock_ok": r_lock <= MAX_LOCK,
        "reflected_not_worse_than_promoted": r_late >= p_late - MAX_LATE_DROP_VS_PROMOTED,
        "reflected_min_sane": r_min >= 0.55,
    }
    promote = all(checks.values())

    print("\n  AGGREGATE")
    print(f"    promoted  late={p_late:.4f}  lock={p_lock:.4f}")
    print(f"    reflected late={r_late:.4f}  lock={r_lock:.4f}  min={r_min:.4f}")
    print("  CHECKS")
    for k, v in checks.items():
        print(f"    {'PASS' if v else 'FAIL'}  {k}")
    print(f"\n  VERDICT: {'PROMOTE reflected → Soft Pack candidate' if promote else 'HOLD — keep promoted default'}")

    report = {
        "exam": "reflected_dna_gate",
        "seeds": SEEDS,
        "steps": STEPS,
        "aggregate": {
            "promoted_late": p_late,
            "reflected_late": r_late,
            "promoted_lock": p_lock,
            "reflected_lock": r_lock,
            "reflected_min": r_min,
        },
        "checks": checks,
        "verdict": "PROMOTE" if promote else "HOLD",
        "rows": rows,
        "note": (
            "PROMOTE means safe to set Soft Pack default DNA to reflected after manual review. "
            "Does not auto-edit KERNEL_v1.py."
        ),
    }
    out = OUT / "exam_reflected_dna.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = OUT / "exam_reflected_dna.md"
    md.write_text(
        f"""# Exam gate — reflected DNA

**Verdict: {report['verdict']}**

| | Promoted | Reflected |
|--|----------|-----------|
| Mean late stab | {p_late:.4f} | {r_late:.4f} |
| Mean lock frac | {p_lock:.4f} | {r_lock:.4f} |

Checks: {checks}

Seeds: {SEEDS}
Steps: {STEPS}

If PROMOTE: manually merge `KERNEL_v1_dna_reflected.json` intuition/wisdom into Soft Pack
or load reflected DNA in HealthEngine — do not silent-overwrite without review.
""",
        encoding="utf-8",
    )
    print(f"  JSON → {out}")
    print(f"  MD   → {md}")
    print("=" * 64)
    return 0 if promote else 1


if __name__ == "__main__":
    raise SystemExit(main())
