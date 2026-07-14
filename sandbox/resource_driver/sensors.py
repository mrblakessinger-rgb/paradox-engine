"""
Host / sim resource sensors — read path only.

Real OS backends (psutil, NVML) plug in later behind try/except.
SimSensors feed exams without host noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HostSnapshot:
    """Normalized 0..1 pressure scores (+ optional raw)."""

    cpu_util: float = 0.0          # 0..1
    mem_pressure: float = 0.0      # 0..1 (1 = near OOM)
    gpu_util: float = 0.0          # 0..1
    gpu_mem_pressure: float = 0.0  # 0..1
    io_wait: float = 0.0           # 0..1
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cpu_util": self.cpu_util,
            "mem_pressure": self.mem_pressure,
            "gpu_util": self.gpu_util,
            "gpu_mem_pressure": self.gpu_mem_pressure,
            "io_wait": self.io_wait,
            "raw": dict(self.raw),
        }


def snapshot_from_dict(d: dict[str, Any]) -> HostSnapshot:
    return HostSnapshot(
        cpu_util=float(d.get("cpu_util", 0.0) or 0.0),
        mem_pressure=float(d.get("mem_pressure", 0.0) or 0.0),
        gpu_util=float(d.get("gpu_util", 0.0) or 0.0),
        gpu_mem_pressure=float(d.get("gpu_mem_pressure", 0.0) or 0.0),
        io_wait=float(d.get("io_wait", 0.0) or 0.0),
        raw=dict(d.get("raw") or {}),
    )


class SimSensors:
    """
    Exam-friendly sensors: set pressures from schedule or World state.
    No OS calls.
    """

    def __init__(self):
        self._snap = HostSnapshot()

    def set(
        self,
        *,
        cpu_util: float = 0.0,
        mem_pressure: float = 0.0,
        gpu_util: float = 0.0,
        gpu_mem_pressure: float = 0.0,
        io_wait: float = 0.0,
    ) -> HostSnapshot:
        self._snap = HostSnapshot(
            cpu_util=float(max(0.0, min(1.0, cpu_util))),
            mem_pressure=float(max(0.0, min(1.0, mem_pressure))),
            gpu_util=float(max(0.0, min(1.0, gpu_util))),
            gpu_mem_pressure=float(max(0.0, min(1.0, gpu_mem_pressure))),
            io_wait=float(max(0.0, min(1.0, io_wait))),
            raw={"source": "sim"},
        )
        return self._snap

    def read(self) -> HostSnapshot:
        return self._snap


class PsutilSensors:
    """
    Optional real host reader. Import psutil only if available.
    Never mutates the system.
    """

    def __init__(self):
        try:
            import psutil  # type: ignore

            self._psutil = psutil
            self.available = True
        except Exception:
            self._psutil = None
            self.available = False

    def read(self) -> HostSnapshot:
        if not self.available or self._psutil is None:
            return HostSnapshot(raw={"source": "psutil_unavailable"})
        psutil = self._psutil
        cpu = float(psutil.cpu_percent(interval=0.0) / 100.0)
        vm = psutil.virtual_memory()
        mem = float(vm.percent / 100.0)
        # io_wait approximate: not always available on Windows
        io_wait = 0.0
        return HostSnapshot(
            cpu_util=cpu,
            mem_pressure=mem,
            gpu_util=0.0,  # NVML optional later
            gpu_mem_pressure=0.0,
            io_wait=io_wait,
            raw={
                "source": "psutil",
                "mem_available_mb": getattr(vm, "available", 0) / (1024 * 1024),
            },
        )
