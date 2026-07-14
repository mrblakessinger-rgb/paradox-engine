"""
Desire 0.96 campaign
====================
1) Train + 5-exam battery @0.96 with host-pressure sim (adapt between)
2) Easy confidence week (mild host, no hard surge)
3) Hell incarnate (toughen_then_hell_eval)
4) 5-exam battery again @0.96
5) Write campaign progress report

  python real_world/run_096_campaign.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def run_py(rel: str, label: str) -> int:
    print("\n" + "#" * 72)
    print(f"# {label}")
    print("#" * 72)
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / rel)], cwd=str(ROOT))
    print(f"  → exit={r.returncode}  wall={(time.time()-t0)/60:.1f} min")
    return int(r.returncode)


def easy_confidence() -> dict:
    """Mild week @0.96 — should clearly hold desire band."""
    from nodes.actuate import apply_shield
    from nodes.engine_loop import HealthEngine
    from paradox_credit_exam import World, apply_plan, apply_resource_intent, bright_week, host_pressure_week
    from sandbox.resource_driver import ResourceDriver, SimSensors, snapshot_from_dict

    TARGET = 0.96
    seeds = [7, 11, 21]
    rows = []
    for seed in seeds:
        eng = HealthEngine(seed=seed, storm_mode="auto", credit_loop=True, target=TARGET)
        eng.paradox.intuition["target_coherence"] = TARGET
        eng.paradox.intuition["recovery_drive"] = 1.4
        eng.paradox.intuition["horizon_sensitivity"] = 1.2
        rng = np.random.default_rng(seed + 5)
        env, bud, empty = bright_week(rng)
        host = host_pressure_week(rng, strength=0.45)
        cpu, mem, gpu, io = host
        w = World(rng=np.random.default_rng(seed + 1))
        sensors = SimSensors()
        driver = ResourceDriver(sensors=sensors)
        stabs, alives, gps = [], [], []
        for t in range(len(env)):
            w.budget_mul, w.tool_empty = bud[t], empty[t]
            w.set_host_pressure(cpu=cpu[t], mem=mem[t], gpu=gpu[t], io=io[t])
            sensors.set(cpu_util=cpu[t], mem_pressure=mem[t], gpu_util=gpu[t], io_wait=io[t])
            out = eng.step_from_metrics(
                success_rate=w.rs(),
                env_load=env[t],
                thrash=w.retries + w.rempty() + 0.2 * cpu[t],
                goodput=w.rgp(),
                budget_remaining=bud[t],
                empty_tool_rate=w.rempty(),
                queue_pressure=0.1 + 0.3 * cpu[t],
            )
            res = driver.step(out["plan"], host=snapshot_from_dict(w.host_snapshot()))
            apply_resource_intent(w, res.intent)
            felt = apply_shield(env[t], out["plan"])
            m = w.step(felt)
            apply_plan(w, out["plan"])
            eng.observe_actual(goodput=m["gp"], alive_frac=m["alive_frac"], stability=out["stability"])
            stabs.append(out["stability"])
            alives.append(m["alive"])
            gps.append(m["gp"])
        eng.end_episode_credit()
        rows.append(
            {
                "stab_late": float(np.mean(stabs[-24:])),
                "alive_end": float(alives[-1]),
                "gp_mean": float(np.mean(gps)),
            }
        )
    summary = {
        "phase": "easy_confidence",
        "target": TARGET,
        "stab_late": float(np.mean([r["stab_late"] for r in rows])),
        "alive_end": float(np.mean([r["alive_end"] for r in rows])),
        "gp_mean": float(np.mean([r["gp_mean"] for r in rows])),
        "pass": all(r["stab_late"] >= TARGET - 0.01 and r["alive_end"] >= 14 for r in rows),
        "seeds": rows,
    }
    print(
        f"  EASY: stab={summary['stab_late']:.3f} alive={summary['alive_end']:.1f} "
        f"gp={summary['gp_mean']:.3f}  {'PASS' if summary['pass'] else 'FAIL'}"
    )
    return summary


def main() -> int:
    print("=" * 72)
    print(" CAMPAIGN · desire 0.96 · host-pressure train → easy → hell → battery")
    print("=" * 72)
    codes = []
    report: dict = {"phases": []}

    # 1) first battery
    codes.append(run_py("real_world/paradox_credit_exam_096_x5.py", "PHASE 1 · 0.96 BATTERY (train+adapt)"))
    b1 = json.loads((OUT / "paradox_credit_exam_096_x5_results.json").read_text(encoding="utf-8"))
    # snapshot as battery_1
    (OUT / "paradox_credit_exam_096_battery1_results.json").write_text(
        json.dumps(b1, indent=2), encoding="utf-8"
    )
    report["phases"].append(
        {
            "name": "battery_1",
            "final_pass": b1.get("final_pass"),
            "e5_stab": b1["exams"][-1]["credit_opt"]["stab_late"],
            "e5_alive": b1["exams"][-1]["credit_opt"]["alive_end"],
            "e5_gp": b1["exams"][-1]["credit_opt"]["gp_mean"],
            "gap": b1["exams"][-1]["credit_opt"]["stab_vs_target"],
            "pre_arm": b1["exams"][-1]["credit_opt"].get("pre_arm_lead"),
            "throttle": b1["exams"][-1]["credit_opt"].get("mean_throttle"),
        }
    )

    # 2) easy confidence
    print("\n" + "#" * 72 + "\n# PHASE 2 · EASY CONFIDENCE\n" + "#" * 72)
    easy = easy_confidence()
    report["phases"].append(easy)
    (OUT / "easy_confidence_096.json").write_text(json.dumps(easy, indent=2), encoding="utf-8")

    # 3) hell
    codes.append(run_py("real_world/toughen_then_hell_eval.py", "PHASE 3 · HELL INCARNATE"))
    hell = json.loads((OUT / "toughen_then_hell_eval.json").read_text(encoding="utf-8"))
    hi = hell.get("eval_matrix", {}).get("C_shell_toughened", {}).get("hell_incarnate", {})
    report["phases"].append(
        {
            "name": "hell_incarnate",
            "C_late": hi.get("late_mean"),
            "C_hold": hi.get("hold_rate"),
            "C_hell_min": hi.get("hell_min_mean"),
            "A_late": hell.get("eval_matrix", {})
            .get("A_base_noshell", {})
            .get("hell_incarnate", {})
            .get("late_mean"),
        }
    )

    # 4) battery again
    codes.append(run_py("real_world/paradox_credit_exam_096_x5.py", "PHASE 4 · 0.96 BATTERY AGAIN"))
    b2 = json.loads((OUT / "paradox_credit_exam_096_x5_results.json").read_text(encoding="utf-8"))
    (OUT / "paradox_credit_exam_096_battery2_results.json").write_text(
        json.dumps(b2, indent=2), encoding="utf-8"
    )
    report["phases"].append(
        {
            "name": "battery_2",
            "final_pass": b2.get("final_pass"),
            "e5_stab": b2["exams"][-1]["credit_opt"]["stab_late"],
            "e5_alive": b2["exams"][-1]["credit_opt"]["alive_end"],
            "e5_gp": b2["exams"][-1]["credit_opt"]["gp_mean"],
            "gap": b2["exams"][-1]["credit_opt"]["stab_vs_target"],
            "pre_arm": b2["exams"][-1]["credit_opt"].get("pre_arm_lead"),
            "throttle": b2["exams"][-1]["credit_opt"].get("mean_throttle"),
            "assessments": b2.get("assessments"),
        }
    )

    # progress verdict
    b1p = report["phases"][0]
    b2p = report["phases"][3]
    easy_p = report["phases"][1]
    hell_p = report["phases"][2]
    # Green = desire band held under host pressure + hell shell still dominant
    green = (
        bool(b2p.get("final_pass") or (b2p.get("e5_stab", 0) >= 0.955 and b2p.get("e5_alive", 0) >= 14))
        and (easy_p.get("stab_late") or 0) >= 0.95
        and (hell_p.get("C_hold") or 0) >= 0.95
        and (hell_p.get("C_late") or 0) >= 0.94
        and (b2p.get("pre_arm") or 0) >= 0.5
    )
    report["campaign_green"] = green
    report["exit_codes"] = codes
    report["recommendation"] = (
        "Soft Pack rebuild + GitHub push OK" if green else "Hold Soft Pack promote — review gaps first"
    )

    # markdown
    lines = [
        "# Desire 0.96 campaign progress",
        "",
        f"**campaign_green:** {green}",
        f"**recommendation:** {report['recommendation']}",
        "",
        "## Phases",
        "",
        f"1. **Battery 1** — stab={b1p.get('e5_stab'):.3f} alive={b1p.get('e5_alive'):.1f} "
        f"gp={b1p.get('e5_gp'):.3f} pass={b1p.get('final_pass')} pre_arm={b1p.get('pre_arm')}",
        f"2. **Easy confidence** — stab={easy_p.get('stab_late'):.3f} alive={easy_p.get('alive_end'):.1f} "
        f"pass={easy_p.get('pass')}",
        f"3. **Hell incarnate (C shell+toughen)** — late={hell_p.get('C_late'):.3f} "
        f"hold={hell_p.get('C_hold')} (A base late={hell_p.get('A_late')})",
        f"4. **Battery 2** — stab={b2p.get('e5_stab'):.3f} alive={b2p.get('e5_alive'):.1f} "
        f"gp={b2p.get('e5_gp'):.3f} pass={b2p.get('final_pass')} pre_arm={b2p.get('pre_arm')} "
        f"throttle={b2p.get('throttle')}",
        "",
        "## Battery 2 assessments",
    ]
    for a in b2p.get("assessments") or []:
        lines.append(f"- {a}")
    lines.append("")
    md = "\n".join(lines)
    (OUT / "campaign_096_progress.md").write_text(md + "\n", encoding="utf-8")
    (OUT / "campaign_096_progress.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + md)
    print(f"\n  → {OUT / 'campaign_096_progress.md'}")
    print(f"  → {OUT / 'campaign_096_progress.json'}")
    print("=" * 72)
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
