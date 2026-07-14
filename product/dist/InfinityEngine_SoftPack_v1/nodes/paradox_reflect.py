"""
Paradox reflection — raw episode scars → wisdom (never swarm trauma)
====================================================================
Usage:
  python -m nodes.paradox_reflect real_world/out/marathon_results.json
  python -m nodes.paradox_reflect real_world/out/marathon_results.json --out KERNEL_v1_dna_reflected.json

Swarm never sees scar JSON. Only exported DNA intuition + wisdom_summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import KERNEL_v1 as K


def load_episode(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    scars = data.get("scars") or data.get("adapter_scars") or []
    segments = data.get("segments") or []
    survived = False
    if segments:
        # long hell if any segment with steps>=60 and final_alive high
        for s in segments:
            if s.get("steps", 0) >= 60 and s.get("final_alive", 0) >= 0.8 * s.get("n_workers", 1):
                survived = True
    meta = {
        "source": str(path),
        "recovery_peak": data.get("recovery_peak"),
        "recovery_late": data.get("recovery_late"),
        "first_soft_break": data.get("first_soft_break"),
        "first_hard_break": data.get("first_hard_break"),
        "final_alive": data.get("final_alive"),
        "survived_long_hell": survived or data.get("first_hard_break") is None,
        "adapter_final": data.get("adapter_final"),
        "target_outer": data.get("target"),
        "n_scars": len(scars),
    }
    return {"scars": scars, "meta": meta, "raw": data}


def reflect(episode_path: Path, out_dna: Path, out_report: Path) -> dict:
    ep = load_episode(episode_path)
    paradox = K.Paradox(K.PROMOTED_DNA)
    paradox.absorb_episode(ep["scars"], episode_meta=ep["meta"])
    report = paradox.compress_scars_to_wisdom(max_intuition_delta=0.06)
    dna = paradox.export_dna()
    dna["reflection"] = {
        "utc": datetime.now(timezone.utc).isoformat(),
        "source_episode": str(episode_path),
        "report": report,
        "note": (
            "Paradox accepted raw scars, compressed to wisdom, cleared raw buffer. "
            "Swarm never received scar log. Not auto-promoted to KERNEL PROMOTED_DNA."
        ),
    }
    out_dna.parent.mkdir(parents=True, exist_ok=True)
    out_dna.write_text(json.dumps(dna, indent=2), encoding="utf-8")

    # Human-readable wisdom sheet
    lines = [
        "# Paradox reflection (not trauma dump)",
        "",
        f"Source: `{episode_path}`",
        f"UTC: {dna['reflection']['utc']}",
        "",
        "## Contract",
        "- Swarm never sees raw episode scars",
        "- Paradox accepts all → compresses → DNA wisdom + tiny intuition nudges",
        "- Anti-lock preserved; target_coherence not trauma-hijacked",
        "",
        "## Wisdom summary (installed as awareness, not diary)",
    ]
    for k, v in dna.get("wisdom_summary", {}).items():
        lines.append(f"- **{k}:** {v}")
    lines.extend(["", "## Intuition deltas (capped)"])
    deltas = report.get("intuition_deltas") or {}
    if not deltas:
        lines.append("- (none)")
    else:
        for k, d in deltas.items():
            lines.append(f"- **{k}:** {d['from']:.4f} → {d['to']:.4f} (Δ {d['delta']:+.4f})")
    lines.extend(
        [
            "",
            "## Episode meta (compressed evidence, not swarm memory)",
            f"- scars absorbed: {report.get('n_scars')}",
            f"- recovery_peak: {ep['meta'].get('recovery_peak')}",
            f"- recovery_late: {ep['meta'].get('recovery_late')}",
            f"- soft_break: {ep['meta'].get('first_soft_break')}",
            f"- hard_break: {ep['meta'].get('first_hard_break')}",
            "",
            f"DNA candidate → `{out_dna}`",
            "",
            "Promote only after multi-seed exam. Soft Pack default stays frozen until then.",
        ]
    )
    out_report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 64)
    print(" PARADOX REFLECTION")
    print("=" * 64)
    print(f"  Scars absorbed : {report.get('n_scars')}")
    print(f"  Wisdom keys    : {list(dna.get('wisdom_summary', {}).keys())}")
    print(f"  Intuition Δ    : {list(deltas.keys())}")
    print(f"  Raw cleared    : {report.get('cleared_raw')}")
    print(f"  DNA candidate  → {out_dna}")
    print(f"  Report         → {out_report}")
    print("=" * 64)
    print("  Swarm was not terrorized. Paradox held the tape, kept the rule.")
    return {"dna": dna, "report": report}


def main() -> int:
    ap = argparse.ArgumentParser(description="Paradox scar → wisdom compressor")
    ap.add_argument("episode_json", type=str, help="Path to marathon_results.json (or similar)")
    ap.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "KERNEL_v1_dna_reflected.json"),
        help="DNA candidate output path",
    )
    ap.add_argument(
        "--report",
        type=str,
        default=str(ROOT / "ops" / "PARADOX_REFLECTION.md"),
        help="Human wisdom report path",
    )
    args = ap.parse_args()
    episode = Path(args.episode_json)
    if not episode.exists():
        print(f"ERROR: missing {episode}")
        return 1
    reflect(episode, Path(args.out), Path(args.report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
