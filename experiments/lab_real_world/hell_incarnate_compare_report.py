"""
Hell incarnate compare — archived ~0.92 baseline vs fresh re-run
================================================================
Baseline: real_world/out/archive_baseline_092/ (earlier, less Paradox awareness)
Fresh:    real_world/out/toughen_then_hell_eval.json + hell_beacons_surge_results.json
Also folds desire-0.95 credit battery if present.

  python real_world/hell_incarnate_compare_report.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
ARCHIVE = OUT / "archive_baseline_092"

SCENARIOS = [
    "mild",
    "cruel",
    "hell_incarnate",
    "flicker",
    "noise_flood",
    "beyond_map",
    "hell_no_hive",
    "hell_solo_paradox",
]
ARMS = [
    "A_base_noshell",
    "B_shell_promoted",
    "C_shell_toughened",
    "D_toughened_noshell",
]


def load(p: Path) -> dict | None:
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def cell(matrix: dict, arm: str, scen: str) -> dict | None:
    m = matrix.get("eval_matrix") or matrix.get("matrix") or matrix
    arm_d = m.get(arm) if isinstance(m, dict) else None
    if not arm_d:
        return None
    return arm_d.get(scen)


def fmt(x, nd=3):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "  n/a "
    return f"{x:.{nd}f}"


def main() -> int:
    base_tough = load(ARCHIVE / "toughen_then_hell_eval.json")
    new_tough = load(OUT / "toughen_then_hell_eval.json")
    base_hell = load(ARCHIVE / "hell_beacons_surge_results.json")
    new_hell = load(OUT / "hell_beacons_surge_results.json")
    credit095 = load(OUT / "paradox_credit_exam_095_x5_results.json")

    lines: list[str] = []
    lines.append("=" * 78)
    lines.append(" HELL INCARNATE COMPARE")
    lines.append(" Baseline archive: less Paradox awareness · target ~0.92")
    lines.append(" Fresh: current DNA + stack re-run (toughen/hell + optional 0.95 credit)")
    lines.append("=" * 78)

    if not base_tough:
        lines.append("\n[WARN] No archive baseline toughen_then_hell_eval.json")
    if not new_tough:
        lines.append("\n[WARN] No fresh toughen_then_hell_eval.json — run toughen_then_hell_eval.py first")

    # --- Toughen matrix: focus hell_incarnate + hold rates ---
    if base_tough and new_tough:
        lines.append("\n## TOUGHEN → HELL EVAL  (late_mean / hold_rate)")
        lines.append(
            f"  baseline target_coherence≈"
            f"{base_tough.get('mean_learned_intuition', {}).get('target_coherence', 0.92)}"
        )
        lines.append(
            f"  fresh    target_coherence≈"
            f"{new_tough.get('mean_learned_intuition', {}).get('target_coherence', '?')}"
        )
        lines.append("")
        lines.append(
            f"  {'arm':22s}  {'scen':16s}  {'base_late':>9}  {'new_late':>9}  {'Δlate':>8}  "
            f"{'base_hold':>9}  {'new_hold':>9}"
        )
        for arm in ARMS:
            for scen in SCENARIOS:
                b = cell(base_tough, arm, scen)
                n = cell(new_tough, arm, scen)
                if not b or not n:
                    continue
                dl = n["late_mean"] - b["late_mean"]
                # only print key scenarios full; others if delta big
                if scen in ("hell_incarnate", "beyond_map", "cruel", "flicker") or abs(dl) > 0.01:
                    lines.append(
                        f"  {arm:22s}  {scen:16s}  {b['late_mean']:9.3f}  {n['late_mean']:9.3f}  "
                        f"{dl:+8.3f}  {b['hold_rate']:9.2f}  {n['hold_rate']:9.2f}"
                    )

        lines.append("\n### hell_incarnate snapshot (all arms)")
        for arm in ARMS:
            b = cell(base_tough, arm, "hell_incarnate")
            n = cell(new_tough, arm, "hell_incarnate")
            if not b or not n:
                continue
            lines.append(
                f"  {arm:22s}  late {b['late_mean']:.3f}→{n['late_mean']:.3f} ({n['late_mean']-b['late_mean']:+.3f})  "
                f"hell_min {b['hell_min_mean']:.3f}→{n['hell_min_mean']:.3f}  "
                f"hold {b['hold_rate']:.0%}→{n['hold_rate']:.0%}"
            )

    # --- Hell beacons: full_defense hell_incarnate ---
    if base_hell and new_hell:
        lines.append("\n## HELL BEACONS SURGE  (target was 0.92 in baseline)")
        bt = base_hell.get("target", 0.92)
        nt = new_hell.get("target", "?")
        lines.append(f"  baseline target={bt}  fresh target={nt}")
        stacks = base_hell.get("stacks") or ["baseline", "full_defense"]
        for scen in ("hell_incarnate", "beyond_map", "cruel"):
            lines.append(f"\n  scenario={scen}")
            bm = (base_hell.get("matrix") or {}).get(scen) or {}
            nm = (new_hell.get("matrix") or {}).get(scen) or {}
            for st in stacks:
                b = bm.get(st)
                n = nm.get(st)
                if not b or not n:
                    continue
                lines.append(
                    f"    {st:16s}  late {b['late_mean']:.3f}→{n['late_mean']:.3f} "
                    f"({n['late_mean']-b['late_mean']:+.3f})  "
                    f"hold {b.get('hold_rate', 0):.0%}→{n.get('hold_rate', 0):.0%}"
                )

    # --- Credit 0.95 battery ---
    if credit095:
        lines.append("\n## DESIRE 0.95 CREDIT BATTERY (current awareness — no 0.92 twin)")
        lines.append(f"  recovery_drive={credit095.get('recovery_drive')}  n_exams={credit095.get('n_exams')}")
        exams = credit095.get("exams") or []
        if exams:
            e1 = exams[0].get("credit_opt") or {}
            e5 = exams[-1].get("credit_opt") or {}
            lines.append(
                f"  e1: gp={e1.get('gp_mean')} alive={e1.get('alive_end')} "
                f"stab={e1.get('stab_late')} post={e1.get('post_surge_alive')} "
                f"rec={e1.get('recovery_frac_post')} pre_arm={e1.get('pre_arm_lead')}"
            )
            lines.append(
                f"  e5: gp={e5.get('gp_mean')} alive={e5.get('alive_end')} "
                f"stab={e5.get('stab_late')} post={e5.get('post_surge_alive')} "
                f"rec={e5.get('recovery_frac_post')} pre_arm={e5.get('pre_arm_lead')} "
                f"surge_str={exams[-1].get('knobs', {}).get('surge_strength')}"
            )
        for a in credit095.get("assessments") or []:
            lines.append(f"  • {a}")
        lc = credit095.get("learning_curve") or {}
        lines.append(f"  learning_curve: {lc}")

    lines.append("\n## NOTES")
    lines.append(
        "  • Archive = earlier hell lab @ ~0.92 with shell/beacons but without today's"
    )
    lines.append(
        "    credit-loop desire band, recovery_drive v2, horizon pre-arm (outer HealthEngine)."
    )
    lines.append(
        "  • toughen/hell scripts still use kernel TARGET from storm_surge_learn (often 0.92);"
    )
    lines.append(
        "    they re-run under *current* KERNEL wisdom/DNA. 0.95 desire is the credit battery."
    )
    lines.append(
        "  • Resource sandbox is a separate fork: sandbox/FORK.md (not in these numbers)."
    )
    lines.append("=" * 78)

    text = "\n".join(lines)
    print(text)
    out_md = OUT / "hell_incarnate_compare_report.md"
    out_json = OUT / "hell_incarnate_compare_report.json"
    out_md.write_text(text + "\n", encoding="utf-8")

    payload = {
        "archive_dir": str(ARCHIVE),
        "has_base_tough": base_tough is not None,
        "has_new_tough": new_tough is not None,
        "has_base_hell": base_hell is not None,
        "has_new_hell": new_hell is not None,
        "has_credit_095": credit095 is not None,
        "hell_incarnate_deltas": {},
    }
    if base_tough and new_tough:
        for arm in ARMS:
            b = cell(base_tough, arm, "hell_incarnate")
            n = cell(new_tough, arm, "hell_incarnate")
            if b and n:
                payload["hell_incarnate_deltas"][arm] = {
                    "late_base": b["late_mean"],
                    "late_new": n["late_mean"],
                    "delta_late": n["late_mean"] - b["late_mean"],
                    "hold_base": b["hold_rate"],
                    "hold_new": n["hold_rate"],
                    "hell_min_base": b["hell_min_mean"],
                    "hell_min_new": n["hell_min_mean"],
                }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  wrote {out_md}")
    print(f"  wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
