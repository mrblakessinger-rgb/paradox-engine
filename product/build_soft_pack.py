"""
Soft Pack dry-run builder
=========================
Stages buyer-facing zip contents. Does NOT include training lab / ops / DNA notes.

  python product/build_soft_pack.py
  python product/build_soft_pack.py --zip
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = Path(__file__).resolve().parent
DIST = PRODUCT / "dist"
PACK_NAME = "InfinityEngine_SoftPack_v1"
STAGE = DIST / PACK_NAME


def wipe(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree_filtered(src: Path, dst: Path, *, skip_names: set[str]) -> None:
    """Copy directory tree skipping __pycache__, .pyc, etc."""
    if not src.is_dir():
        raise FileNotFoundError(src)
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in skip_names for part in rel.parts):
            continue
        if p.suffix in {".pyc", ".pyo"}:
            continue
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


SKIP = {"__pycache__", ".git", ".pytest_cache"}


README = f"""# Infinity Engine Soft Pack v1

**Price:** $149 personal · **Built:** {date.today().isoformat()}  
**Promise:** Measured health control for multi-agent / worker systems under load storms.  
**Doctrine:** You buy the lift. Internals stay sealed.

## OPEN THE PROOFS FIRST (already in this zip)

You do **not** have to take our word for it. Charts + HTML case studies are included.

1. Double-click **`START_HERE.html`**  
   **or** open folder **`OPEN_THESE_PROOFS/`**

| File | What you see |
|------|----------------|
| `OPEN_THESE_PROOFS/A_agent_fleet.html` | Baseline **0.47** → Engine **0.69** (**+0.22**) |
| `OPEN_THESE_PROOFS/B_job_queue.html` | Baseline **0.51** → Engine **0.74** (**+0.23**) |
| `OPEN_THESE_PROOFS/C_rate_limit.html` | Goodput **0.02** → **0.25** (**+0.24**) |
| `OPEN_THESE_PROOFS/*_chart.png` | The actual comparison plots |

Full runners (re-generate numbers yourself) live under `portfolio/proof_*`.

## Then re-run (optional, proves it on your machine)

```bat
pip install -r REQUIREMENTS.txt
cd portfolio\\proof_a_agent_fleet
python run_proof_a.py
start out\\proof_a_case_study.html
```

Expect ~**+0.22** again. Same for B and C.

## What's inside

| Path | What |
|------|------|
| **`START_HERE.html`** | Front door — links to all three proofs |
| **`OPEN_THESE_PROOFS/`** | Pre-built HTML + PNG results (no Python needed) |
| `portfolio/proof_a_*` | Full agent-fleet proof (code + out/) |
| `portfolio/proof_b_*` | Full job-queue proof |
| `portfolio/proof_c_*` | Full API rate-limit proof |
| `KERNEL_v1.py` | Frozen kernel |
| `nodes/` | Ingest + actuate + HealthEngine wire-in |
| `plugins/` | Drop-in adapters: fleet, queue, API, LangGraph, CrewAI |
| `portfolio/ONE_PAGER.html` | Shareable one-pager |
| `INTEGRATION.md` | Wire your metrics |
| `LICENSE_PERSONAL.txt` | Personal-use license |

## What is NOT inside (on purpose)

- Training / DNA breeding lab
- Architecture deep-dives
- Consulting hours
- Live host OS control (CPU/GPU/RAM drivers) — optional sandbox is lab-only; Soft Pack stays intent-level via storm/recovery/horizon

## Health stack included (v1 refresh)

- Auto storm pack + beacons
- Credit loop (forecast vs actual)
- Recovery desire after load drop
- Horizon scout (leading indicators / pre-arm)
- Desire band via `target_coherence` (Soft Pack default remains conservative; lab may run higher)

## Support boundary

OK: install, open proofs, re-run, map success rate → ingest  
Out of scope: every internal lever / re-derive DNA

## Layout note

Proof runners expect `KERNEL_v1.py` at pack root (two levels up from `portfolio/proof_*/`).
"""

QUICKSTART = """# Soft Pack — Quickstart

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
cd portfolio\\proof_a_agent_fleet
python run_proof_a.py
start out\\proof_a_case_study.html
```
Expect green Δ ~+0.22

## 3. Re-run B / C
```bat
cd portfolio\\proof_b_job_queue
python run_proof_b.py

cd portfolio\\proof_c_rate_limit
python run_proof_c.py
```

## 4. Kernel heartbeat
```bat
python KERNEL_v1.py --demo 40
python nodes\\demo_nodes.py
```

## 5. Wire your system
Read `INTEGRATION.md` — ingest → HealthEngine → actuate.

## 6. Plugins (easiest)
```bat
python -m plugins.examples.minimal_all
```
See `plugins/README.md` — Fleet / Queue / API / LangGraph / CrewAI drop-ins.
"""

LICENSE = """Infinity Engine Soft Pack — Personal License (v1)
================================================

Copyright (c) 2026 Infinity Engine author. All rights reserved.

1. GRANT
   You may use this Soft Pack on machines you control for personal or
   internal evaluation and production use by a single licensee.

2. NO REDISTRIBUTION
   You may not resell, republish, sublicense, or share the pack files
   (including KERNEL_v1.py and nodes/) as your own product or in a
   competing pack without written permission.

3. NO TRAINING LAB
   This pack is a frozen runtime + demos. It does not grant rights to
   any separate training, exam, or DNA-evolution materials.

4. NO WARRANTY
   Provided "as is". Measured demo lifts are reproducible under the
   included seeds/scripts; your production results will vary with
   your system. Author is not liable for consequential damages.

5. ATTRIBUTION
   Optional but appreciated when you publish numbers derived from the
   included proofs.

6. COMMERCIAL REDISTRIBUTION / OEM
   Contact the author for a separate license.

Questions: install and run support only (see README).
"""

MANIFEST_NOTE = """# Soft Pack dry-run manifest

Generated by `product/build_soft_pack.py`.

## Included
- START_HERE.html + OPEN_THESE_PROOFS/ (pre-built HTML+PNG — no Python)
- KERNEL_v1.py
- nodes/ (public wire-in only)
- portfolio/proof_a, proof_b, proof_c (full runners + out/)
- portfolio/ONE_PAGER.html
- INTEGRATION.md, BUYER_LANGUAGE.md, README.md, QUICKSTART.md
- LICENSE_PERSONAL.txt, REQUIREMENTS.txt

## Excluded (moat)
- ops/, product/ads/, training lab, __pycache__

## Buyer check
1. Open START_HERE.html — see three proofs
2. Optional: python portfolio/proof_a_agent_fleet/run_proof_a.py
"""

# Pre-built proof front door (copied charts + HTML from portfolio out/)
PROOF_BUNDLE = [
    {
        "key": "A",
        "title": "Proof A — Agent fleet",
        "lift": "+0.22 success",
        "src_dir": "portfolio/proof_a_agent_fleet/out",
        "html": "proof_a_case_study.html",
        "png": "proof_a_comparison.png",
        "dst_html": "A_agent_fleet.html",
        "dst_png": "A_agent_fleet_chart.png",
    },
    {
        "key": "B",
        "title": "Proof B — Job queue",
        "lift": "+0.23 success",
        "src_dir": "portfolio/proof_b_job_queue/out",
        "html": "proof_b_case_study.html",
        "png": "proof_b_comparison.png",
        "dst_html": "B_job_queue.html",
        "dst_png": "B_job_queue_chart.png",
    },
    {
        "key": "C",
        "title": "Proof C — API rate-limit",
        "lift": "+0.24 goodput",
        "src_dir": "portfolio/proof_c_rate_limit/out",
        "html": "proof_c_case_study.html",
        "png": "proof_c_comparison.png",
        "dst_html": "C_rate_limit.html",
        "dst_png": "C_rate_limit_chart.png",
    },
]


def write_proof_front_door(stage: Path) -> None:
    """Copy proof HTML/PNG to OPEN_THESE_PROOFS/ and write START_HERE.html."""
    out = stage / "OPEN_THESE_PROOFS"
    out.mkdir(parents=True, exist_ok=True)
    cards = []
    for p in PROOF_BUNDLE:
        src = ROOT / p["src_dir"]
        html_src = src / p["html"]
        png_src = src / p["png"]
        if not html_src.exists() or not png_src.exists():
            print(f"  WARN: missing proof artifacts for {p['key']} at {src}")
            continue
        # HTML may reference local png name — rewrite to dst png name
        html_text = html_src.read_text(encoding="utf-8")
        html_text = html_text.replace(p["png"], p["dst_png"])
        # also common src= patterns without path
        (out / p["dst_html"]).write_text(html_text, encoding="utf-8")
        copy_file(png_src, out / p["dst_png"])
        cards.append(p)

    index = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Soft Pack — Open these proofs</title>
<style>
body{margin:0;padding:32px 20px;background:#0b0f14;color:#e8eef7;font-family:Segoe UI,system-ui,sans-serif;max-width:820px;margin-inline:auto}
h1{margin:0 0 8px} .sub{color:#8b9bb0;margin:0 0 22px}
.grid{display:grid;gap:12px}
a.card{display:block;background:#121a24;border:1px solid #243044;border-radius:12px;padding:16px;text-decoration:none;color:inherit}
a.card:hover{border-color:#3a6}
.ok{color:#5dffb0;font-weight:700;font-size:1.2rem}
p{margin:6px 0 0;color:#8b9bb0;font-size:.9rem}
img{max-width:100%;border-radius:8px;margin-top:10px;border:1px solid #243044}
</style></head><body>
<h1>Proofs included — not just claimed</h1>
<p class="sub">Pre-built results from this Soft Pack. Click any card. Re-run scripts live under <code>portfolio/</code>.</p>
<div class="grid">
"""
    for p in cards:
        index += f"""<a class="card" href="{p['dst_html']}">
  <div class="ok">{p['lift']}</div>
  <strong>{p['title']}</strong>
  <p>Open full case study HTML</p>
  <img src="{p['dst_png']}" alt="{p['title']} chart"/>
</a>
"""
    index += """</div>
<p class="sub" style="margin-top:24px">Re-run: <code>portfolio/proof_a_agent_fleet/run_proof_a.py</code> (and B/C). Kernel at pack root.</p>
</body></html>"""
    (out / "index.html").write_text(index, encoding="utf-8")

    start = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta http-equiv="refresh" content="0; url=OPEN_THESE_PROOFS/index.html"/>
<title>Soft Pack — Start here</title>
<style>body{font-family:Segoe UI,sans-serif;background:#0b0f14;color:#e8eef7;padding:40px}
a{color:#5dffb0}</style></head>
<body>
<h1>Infinity Engine Soft Pack</h1>
<p>If you are not redirected, open:</p>
<p><a href="OPEN_THESE_PROOFS/index.html"><b>OPEN_THESE_PROOFS / index.html</b></a></p>
<p style="color:#8b9bb0">Real proof charts for A, B, and C — already in this zip.</p>
</body></html>"""
    (stage / "START_HERE.html").write_text(start, encoding="utf-8")


def stage() -> Path:
    wipe(STAGE)
    STAGE.mkdir(parents=True)

    # Kernel
    copy_file(ROOT / "KERNEL_v1.py", STAGE / "KERNEL_v1.py")

    # Nodes (no pycache)
    copy_tree_filtered(ROOT / "nodes", STAGE / "nodes", skip_names=SKIP)

    # Plugins — drop-in adapters (fleet / queue / api / langgraph / crewai)
    if (ROOT / "plugins").is_dir():
        copy_tree_filtered(ROOT / "plugins", STAGE / "plugins", skip_names=SKIP)

    # Portfolio proofs + one-pager
    port = STAGE / "portfolio"
    port.mkdir(parents=True, exist_ok=True)
    for name in (
        "proof_a_agent_fleet",
        "proof_b_job_queue",
        "proof_c_rate_limit",
    ):
        src = ROOT / "portfolio" / name
        if not src.exists():
            print(f"  WARN: missing {src}")
            continue
        copy_tree_filtered(src, port / name, skip_names=SKIP)

    one = ROOT / "portfolio" / "ONE_PAGER.html"
    if one.exists():
        copy_file(one, port / "ONE_PAGER.html")

    # Front door: pre-built proof HTML + charts (no "trust us")
    write_proof_front_door(STAGE)

    # Docs (prefer product/, fall back to repo root)
    for name in ("INTEGRATION.md", "BUYER_LANGUAGE.md"):
        src = PRODUCT / name if (PRODUCT / name).exists() else ROOT / name
        if src.exists():
            copy_file(src, STAGE / name)
        else:
            print(f"  WARN: missing {name}")

    (STAGE / "README.md").write_text(README, encoding="utf-8")
    (STAGE / "QUICKSTART.md").write_text(QUICKSTART, encoding="utf-8")
    (STAGE / "LICENSE_PERSONAL.txt").write_text(LICENSE, encoding="utf-8")
    (STAGE / "REQUIREMENTS.txt").write_text("numpy>=1.24\nmatplotlib>=3.7\n", encoding="utf-8")
    (STAGE / "MANIFEST_DRY_RUN.md").write_text(MANIFEST_NOTE, encoding="utf-8")

    return STAGE


def make_zip(stage: Path) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    zpath = DIST / f"{PACK_NAME}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in stage.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=str(Path(PACK_NAME) / p.relative_to(stage)))
    return zpath


def count_files(stage: Path) -> int:
    return sum(1 for p in stage.rglob("*") if p.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="store_true", help="Also write .zip")
    ap.add_argument("--no-verify", action="store_true", help="Skip import smoke")
    args = ap.parse_args()

    print("=" * 64)
    print(" SOFT PACK DRY-RUN BUILD")
    print("=" * 64)
    print(f"  Root  : {ROOT}")
    print(f"  Stage : {STAGE}")

    stage_path = stage()
    n = count_files(stage_path)
    print(f"  Files : {n}")

    # List top-level
    print("\n  Top-level:")
    for p in sorted(stage_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        mark = " " if p.is_file() else "/"
        print(f"    {p.name}{mark if p.is_dir() else ''}")

    if not args.no_verify:
        print("\n  Verify imports from staged tree…")
        sys.path.insert(0, str(stage_path))
        # fresh import
        for mod in list(sys.modules):
            if mod == "KERNEL_v1" or mod.startswith("nodes"):
                del sys.modules[mod]
        import KERNEL_v1 as K  # noqa: F401
        from nodes.engine_loop import HealthEngine  # noqa: F401
        from nodes.ingest import to_interference

        I = to_interference(success_rate=0.6, env_load=1.5)
        eng = HealthEngine(seed=1)
        out = eng.step(I, success_rate=0.6)
        print(f"    KERNEL {K.KERNEL_VERSION} · I={I:.3f} · stab={out['stability']:.3f}")
        assert stage_path.joinpath("portfolio", "proof_a_agent_fleet", "run_proof_a.py").exists()
        print("    proof_a runner present")
        print("    VERIFY OK")

    zpath = None
    if args.zip:
        zpath = make_zip(stage_path)
        mb = zpath.stat().st_size / (1024 * 1024)
        print(f"\n  ZIP → {zpath}")
        print(f"  Size: {mb:.2f} MB")

    print("\n" + "=" * 64)
    print("  DRY-RUN COMPLETE")
    print(f"  Folder: {stage_path}")
    if zpath:
        print(f"  Zip   : {zpath}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
