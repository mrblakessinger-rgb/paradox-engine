# Fork freeze — Resource control vs Paradox core

**Date locked:** session after desire-0.95 + recovery_drive + horizon scout.

## Boundary (do not blur)

| Lane | Owns | Does not own |
|------|------|----------------|
| **KERNEL DNA** | Swarm physics, frozen intuition promos | Host OS, GPU, RAM, cgroups |
| **Soft Pack / HealthEngine** | Desire, credit, recovery, horizon, **abstract intents** | `psutil`, NVML, process kill |
| **sandbox/resource_driver** | Host sensors + actuators, safety rails, dry-run | Swarm DNA, Soft Pack default body |
| **Exam World (sim)** | Fake `cpu_pressure` / `mem_pressure` for policy learning | Real machines |

## Rule

> **Paradox decides *what* to protect and *how hard*.**  
> **Resource sandbox decides *which knobs on this machine*.**

Paradox may emit:

- `compute_throttle` — cut concurrency / workers / batch
- `memory_shed` — defer fat work, fail-closed on heavy payloads
- `gpu_defer` — queue inference, no new heavy GPU jobs
- `io_cool` — slow disk/network stampede

Sandbox maps those intents → host (or dry-run log). **Never** import OS control into `KERNEL_v1.py`.

## Build order

1. ✅ Freeze this fork (this file + package scaffold)
2. Sim pressure in World exams (optional next)
3. Wire horizon sensors from sandbox **read-only** profile
4. Dry-run apply → then real limits behind allowlist

## Soft Pack

Default Soft Pack **stays free of host privilege**. Resource driver is optional add-on / lab lane.
