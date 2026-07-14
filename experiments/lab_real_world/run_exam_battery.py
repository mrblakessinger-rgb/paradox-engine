"""
Exam battery — current Paradox awareness stack
==============================================
Runs (in order):

  1) paradox_credit_exam_095_x5   desire 0.95 · recovery · horizon · credit
  2) toughen_then_hell_eval       kernel hell matrix (re-run vs archived 0.92)
  3) hell_beacons_surge_demo      beacons/surge hell stacks
  4) hell_incarnate_compare_report  archive 0.92 vs fresh results

  python real_world/run_exam_battery.py
  python real_world/run_exam_battery.py --skip-hell   # credit only
  python real_world/run_exam_battery.py --only-compare
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ARCHIVE = OUT / "archive_baseline_092"


def run_mod(rel: str, label: str) -> int:
    print("\n" + "#" * 72)
    print(f"# {label}")
    print(f"# python {rel}")
    print("#" * 72)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / rel)], cwd=str(ROOT))
    dt = time.time() - t0
    print(f"\n  → exit={r.returncode}  wall={dt/60:.1f} min")
    return int(r.returncode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-hell", action="store_true", help="Only 0.95 credit battery")
    ap.add_argument("--only-compare", action="store_true", help="Only write compare report")
    ap.add_argument("--skip-credit", action="store_true")
    args = ap.parse_args()

    print("=" * 72)
    print(" EXAM BATTERY · current stack (recovery + horizon + credit + desire band)")
    print(f" ROOT={ROOT}")
    print(f" ARCHIVE baseline={ARCHIVE}")
    print("=" * 72)

    codes = []
    if args.only_compare:
        codes.append(run_mod("real_world/hell_incarnate_compare_report.py", "COMPARE REPORT"))
        return 0 if all(c == 0 for c in codes) else 1

    if not args.skip_credit:
        codes.append(
            run_mod("real_world/paradox_credit_exam_095_x5.py", "CREDIT 0.95 ×5 EXAMS")
        )

    if not args.skip_hell:
        codes.append(run_mod("real_world/toughen_then_hell_eval.py", "TOUGHEN → HELL EVAL"))
        codes.append(run_mod("real_world/hell_beacons_surge_demo.py", "HELL BEACONS SURGE"))
        codes.append(
            run_mod("real_world/hell_incarnate_compare_report.py", "COMPARE vs ARCHIVE 0.92")
        )

    # summary stamp
    stamp = {
        "battery": "current_awareness",
        "modules": [
            "paradox_credit_exam_095_x5",
            "toughen_then_hell_eval",
            "hell_beacons_surge_demo",
            "hell_incarnate_compare_report",
        ],
        "exit_codes": codes,
        "archive": str(ARCHIVE),
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "exam_battery_last_run.json").write_text(json.dumps(stamp, indent=2), encoding="utf-8")
    print("\n" + "=" * 72)
    print(f" BATTERY DONE  exits={codes}")
    print("=" * 72)
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
