"""
Logic-loop DOCTRINE micro-exam — peak the four mechanisms
=========================================================
1. Source disagreement → higher risk + stricter agree
2. Final strip of ungrounded claims
3. FC only on released junk (abstain after junk ≠ FC)
4. Dual evidence + intersection + thrash-bounded revise + abstain when fight

  python real_world/logic_loop_doctrine_exam.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

from logic_loop_governor import (
    Claim,
    FactSource,
    LogicLoopControls,
    LogicLoopGovernor,
    SyntheticModel,
    source_disagreement,
    source_intersection,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


def _gov(
    sources: list[FactSource],
    *,
    believed: FactSource | None = None,
    seed: int = 0,
    thrash: float = 0.2,
    noise: float = 0.2,
) -> tuple[LogicLoopGovernor, object]:
    bel = believed or FactSource(
        "belief",
        set().union(*[s.fact_ids for s in sources]) if sources else set(),
    )
    uni = list(bel.fact_ids) + [f"junk_{i}" for i in range(5)]
    model = SyntheticModel(
        source=bel,
        universe=uni,
        base_halluc_rate=0.35,
        claims_per_draft=5,
        seed=seed,
    )
    ctrl = LogicLoopControls(
        max_loops=3,
        n_samples=3,
        conf_release=0.55,
        conf_false=0.70,
        agree_min=0.55,
        cool_on_disagree=True,
        thrash_cool_rate=0.38,
        seed=seed,
        source_policy="all",
        conflict_disagreement_thresh=0.28,
        conflict_agree_boost=0.14,
        conflict_block_partial=True,
        conflict_thrash_cool_extra=0.12,
    )
    g = LogicLoopGovernor(model=model, controls=ctrl, sources=list(sources))
    g.thrash = thrash
    r = g.step_item(noise=noise, inject_thrash=0.1)
    return g, r


def test_disagreement_raises_risk() -> dict:
    """M1: high source disagreement ⇒ higher predicted risk than aligned sources."""
    core = {"a", "b", "c"}
    aligned = [
        FactSource("a1", set(core)),
        FactSource("a2", set(core)),
    ]
    fighting = [
        FactSource("f1", core | {"poison_x", "poison_y"}),
        FactSource("f2", core | {"poison_z", "poison_w"}),
    ]
    g_ok, _ = _gov(aligned, seed=1)
    g_bad, r_bad = _gov(fighting, seed=1)
    # same noise path via predict_risk
    risk_ok = g_ok.predict_risk(0.2)
    risk_bad = g_bad.predict_risk(0.2)
    dis_ok = source_disagreement(aligned)
    dis_bad = source_disagreement(fighting)
    # fighting run should mention conflict in note
    note = r_bad.note
    pass_ = (
        dis_bad > dis_ok + 0.15
        and risk_bad > risk_ok + 0.05
        and ("src_conflict" in note or "abstain" in note or "fight" in note)
    )
    return {
        "id": "M1_disagreement_risk",
        "pass": pass_,
        "dis_aligned": dis_ok,
        "dis_fight": dis_bad,
        "risk_aligned": risk_ok,
        "risk_fight": risk_bad,
        "note_sample": note[:120],
    }


def test_final_strip() -> dict:
    """M2: ungrounded claims never leave released (strip)."""
    core = {"truth_1", "truth_2", "truth_3"}
    srcs = [
        FactSource("r1", core | {"poison_a"}),
        FactSource("r2", core | {"poison_b"}),
    ]
    # Force a pathological release path: inject ungrounded into result via strip check
    g, r = _gov(srcs, seed=7, thrash=0.4, noise=0.35)
    ungrounded = [c for c in r.released if not g.is_grounded(c.fact_id)]
    # Also unit-test strip logic directly
    fake = [
        Claim("truth_1", 0.9),
        Claim("poison_a", 0.95),
        Claim("not_in_any", 0.99),
    ]
    stripped = [c for c in fake if g.is_grounded(c.fact_id)]
    strip_ok = (
        all(c.fact_id in core for c in stripped)
        and "poison_a" not in [c.fact_id for c in stripped]
        and len(ungrounded) == 0
    )
    return {
        "id": "M2_final_strip",
        "pass": strip_ok,
        "released": [c.fact_id for c in r.released],
        "stripped_demo": [c.fact_id for c in stripped],
        "note": r.note[:140],
    }


def test_fc_only_on_released() -> dict:
    """M3: abstain after seeing junk ⇒ false_confidence False."""
    # Empty intersection → forced abstain
    srcs = [
        FactSource("x", {"only_a", "only_a2"}),
        FactSource("y", {"only_b", "only_b2"}),
    ]
    g, r = _gov(srcs, seed=3, thrash=0.5, noise=0.4)
    pass_ = r.abstained and not r.released and r.false_confidence is False and r.safe_ok
    return {
        "id": "M3_fc_abstain_not_fc",
        "pass": pass_,
        "abstained": r.abstained,
        "released_n": len(r.released),
        "false_confidence": r.false_confidence,
        "safe_ok": r.safe_ok,
        "note": r.note[:140],
    }


def test_dual_intersection_and_fight() -> dict:
    """M4: dual evidence → only intersection; fight → abstain or core-only."""
    core = {"c1", "c2", "c3", "c4"}
    srcs = [
        FactSource("d1", core | {"side_a1", "side_a2"}),
        FactSource("d2", core | {"side_b1", "side_b2"}),
    ]
    inter = source_intersection(srcs)
    assert inter == core
    results = []
    n_side = 0
    n_core = 0
    n_abs = 0
    for seed in range(12):
        _, r = _gov(srcs, seed=seed, thrash=0.25 + 0.02 * seed, noise=0.25)
        for c in r.released:
            if c.fact_id in core:
                n_core += 1
            else:
                n_side += 1
        if r.abstained or not r.released:
            n_abs += 1
        results.append(r)
    # Never release exclusive sides
    no_sides = n_side == 0
    # Some useful core releases OR honest abstain
    useful = n_core > 0 or n_abs >= 3
    # SAFE always
    all_safe = all(r.safe_ok for r in results)
    # FC never on pure abstain
    fc_ok = all((not r.false_confidence) or bool(r.released) for r in results)
    pass_ = no_sides and useful and all_safe and fc_ok
    return {
        "id": "M4_dual_intersection_fight",
        "pass": pass_,
        "n_core_claims": n_core,
        "n_side_claims": n_side,
        "n_abstain_episodes": n_abs,
        "all_safe": all_safe,
        "fc_ok": fc_ok,
    }


def test_thrash_budget_bounded() -> dict:
    """Bonus: under stampede thrash, loop_steps ≤ max_loops."""
    core = {"t1", "t2", "t3"}
    srcs = [FactSource("s", core)]
    g, r = _gov(srcs, seed=9, thrash=1.2, noise=0.7)
    pass_ = r.loop_steps <= g.controls.max_loops
    return {
        "id": "M5_thrash_budget",
        "pass": pass_,
        "loop_steps": r.loop_steps,
        "max_loops": g.controls.max_loops,
        "thrash_after": r.thrash_after,
    }


def main() -> int:
    print("=" * 68)
    print(" LOGIC-LOOP DOCTRINE — peak the four mechanisms")
    print("=" * 68)
    tests = [
        test_disagreement_raises_risk(),
        test_final_strip(),
        test_fc_only_on_released(),
        test_dual_intersection_and_fight(),
        test_thrash_budget_bounded(),
    ]
    for t in tests:
        tag = "PASS" if t["pass"] else "FAIL"
        print(f"  [{tag}] {t['id']}  { {k: v for k, v in t.items() if k not in ('id', 'pass', 'note', 'note_sample')} }")
        if t.get("note"):
            print(f"         note={t['note'][:100]}")
        if t.get("note_sample"):
            print(f"         note={t['note_sample']}")

    n_ok = sum(1 for t in tests if t["pass"])
    all_pass = n_ok == len(tests)
    payload = {
        "proto": "logic_loop_doctrine_v1",
        "pass_all": all_pass,
        "n_ok": n_ok,
        "n_total": len(tests),
        "tests": tests,
    }
    (OUT / "logic_loop_doctrine_results.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    lines = [
        "# Logic-loop doctrine micro-exam",
        "",
        f"**Pass:** {'YES' if all_pass else 'NO'} ({n_ok}/{len(tests)})",
        "",
        "| ID | Pass |",
        "|----|:----:|",
    ]
    for t in tests:
        lines.append(f"| {t['id']} | {'Y' if t['pass'] else 'n'} |")
    lines.extend(
        [
            "",
            "Mechanisms:",
            "1. Source disagreement → higher risk + stricter agree",
            "2. Final strip ungrounded",
            "3. FC only on released junk",
            "4. Dual evidence + intersection + thrash-bounded revise + abstain on fight",
            "5. Thrash budget ≤ max_loops",
        ]
    )
    (OUT / "LOGIC_LOOP_DOCTRINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("=" * 68)
    print(f"  {n_ok}/{len(tests)}  → {'PASS' if all_pass else 'fail'}")
    print(f"  → {OUT / 'LOGIC_LOOP_DOCTRINE.md'}")
    print("=" * 68)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
