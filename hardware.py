import os
import sys
import time
import platform
import subprocess
import shutil
import csv
import io
import re
import threading
from typing import Any

try:
    import psutil
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
except Exception:
    psutil = None

_stats_cache: dict[str, Any] = {
    "ts": 0.0,
    "data": None,
}
_cache_lock = threading.Lock()
_win_gpu_perf_cache: dict[str, Any] = {
    "ts": 0.0,
    "util": {},
    "vram": {},
}


def _get_cpu_brand() -> str:
    """Retrieves human-readable CPU brand model name."""
    try:
        if platform.system() == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return val.strip()
        elif platform.system() == "Linux":
            if os.path.exists("/proc/cpuinfo"):
                with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"


def _get_cpu_temperature() -> float | None:
    """Attempts to read CPU temperature across Linux/Windows."""
    if not psutil:
        return None
    try:
        if hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "acpitz"):
                    if key in temps and temps[key]:
                        return round(temps[key][0].current, 1)
                for entries in temps.values():
                    if entries:
                        return round(entries[0].current, 1)
    except Exception:
        pass
    return None


def get_cpu_stats() -> dict[str, Any]:
    if not psutil:
        return {
            "brand": _get_cpu_brand(),
            "percent": 0.0,
            "cores": [],
            "count_physical": os.cpu_count() or 1,
            "count_logical": os.cpu_count() or 1,
            "freq_mhz": None,
            "temp_c": None,
        }

    try:
        # non-blocking sample
        overall_pct = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:
        overall_pct = 0.0
        per_core = []

    freq_mhz = None
    try:
        cfreq = psutil.cpu_freq()
        if cfreq:
            freq_mhz = round(cfreq.current, 0)
    except Exception:
        pass

    return {
        "brand": _get_cpu_brand(),
        "percent": round(overall_pct, 1),
        "cores": [round(c, 1) for c in per_core],
        "count_physical": psutil.cpu_count(logical=False) or os.cpu_count() or 1,
        "count_logical": psutil.cpu_count(logical=True) or os.cpu_count() or 1,
        "freq_mhz": freq_mhz,
        "temp_c": _get_cpu_temperature(),
    }


def get_ram_stats() -> dict[str, Any]:
    if not psutil:
        return {
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "percent": 0.0,
            "swap_total_bytes": 0,
            "swap_used_bytes": 0,
            "swap_percent": 0.0,
        }

    try:
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        return {
            "total_bytes": vm.total,
            "used_bytes": vm.used,
            "free_bytes": vm.available,
            "percent": round(vm.percent, 1),
            "swap_total_bytes": sm.total,
            "swap_used_bytes": sm.used,
            "swap_percent": round(sm.percent, 1),
        }
    except Exception:
        return {
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "percent": 0.0,
            "swap_total_bytes": 0,
            "swap_used_bytes": 0,
            "swap_percent": 0.0,
        }


# ==============================================================================
# GPU Monitoring (Intel Battlemage/Arc, NVIDIA, AMD)
# ==============================================================================

def _query_nvidia_smi() -> list[dict[str, Any]]:
    """Queries NVIDIA GPUs via nvidia-smi CLI."""
    if not shutil.which("nvidia-smi"):
        # Check standard Windows paths if not in PATH
        for p in (
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ):
            if os.path.exists(p):
                shutil_cmd = p
                break
        else:
            return []
    else:
        shutil_cmd = "nvidia-smi"

    try:
        cmd = [
            shutil_cmd,
            "--query-gpu=index,name,driver_version,utilization.gpu,utilization.memory,memory.total,memory.used,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits",
        ]
        out = subprocess.check_output(cmd, text=True, timeout=2.0)
        res = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 9:
                idx = parts[0]
                name = parts[1]
                drv = parts[2]
                try:
                    gpu_util = float(parts[3])
                except ValueError:
                    gpu_util = 0.0
                try:
                    mem_util = float(parts[4])
                except ValueError:
                    mem_util = 0.0
                try:
                    mem_tot = int(float(parts[5]) * 1024 * 1024)
                except ValueError:
                    mem_tot = 0
                try:
                    mem_used = int(float(parts[6]) * 1024 * 1024)
                except ValueError:
                    mem_used = 0
                temp_c = None
                if parts[7] != "[N/A]":
                    try:
                        temp_c = float(parts[7])
                    except ValueError:
                        pass
                power_w = None
                if parts[8] != "[N/A]":
                    try:
                        power_w = float(parts[8])
                    except ValueError:
                        pass

                res.append({
                    "id": f"nvidia-{idx}",
                    "name": name,
                    "vendor": "nvidia",
                    "driver_version": drv,
                    "utilization_gpu_percent": round(gpu_util, 1),
                    "memory_percent": round(mem_util, 1),
                    "memory_total_bytes": mem_tot,
                    "memory_used_bytes": mem_used,
                    "temperature_c": temp_c,
                    "power_watts": power_w,
                    "source": "nvidia-smi",
                })
        return res
    except Exception:
        return []


def _update_windows_gpu_perf_cache() -> None:
    """Background helper to update Windows GPU Engine and Adapter Memory counters."""
    global _win_gpu_perf_cache
    now = time.time()
    if now - _win_gpu_perf_cache["ts"] < 3.0:
        return

    try:
        cmd = [
            "typeperf",
            r"\GPU Engine(*engtype_3D*)\Utilization Percentage",
            r"\GPU Adapter Memory(*)\Dedicated Usage",
            "-sc", "1",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
        lines = [l.strip() for l in p.stdout.splitlines() if l.strip() and not l.startswith("Exiting")]
        if len(lines) >= 2:
            reader = csv.reader(io.StringIO(lines[0] + "\n" + lines[1]))
            headers = next(reader)
            values = next(reader)
            new_util: dict[str, float] = {}
            new_vram: dict[str, int] = {}

            for h, v in zip(headers, values):
                m = re.search(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)", h)
                if not m:
                    continue
                luid = m.group(1).lower()
                try:
                    val = float(v)
                except ValueError:
                    continue

                if "utilization percentage" in h.lower():
                    new_util[luid] = new_util.get(luid, 0.0) + val
                elif "dedicated usage" in h.lower():
                    new_vram[luid] = max(new_vram.get(luid, 0), int(val))

            _win_gpu_perf_cache = {
                "ts": now,
                "util": {k: round(v, 1) for k, v in new_util.items()},
                "vram": new_vram,
            }
    except Exception:
        pass


def _get_windows_adapters() -> list[dict[str, Any]]:
    """Enumerates display adapters from Windows Registry."""
    adapters = []
    if platform.system() != "Windows":
        return adapters

    key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        sub_count = winreg.QueryInfoKey(key)[0]
        for i in range(sub_count):
            sub_name = winreg.EnumKey(key, i)
            if not sub_name.isdigit():
                continue
            sub = winreg.OpenKey(key, sub_name)
            try:
                desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                low = desc.lower()
                # Exclude virtual / mirror adapters
                if any(v in low for v in ("virtual", "remote", "rdp", "citrix", "meta virtual", "basic display", "vbox", "vmware")):
                    continue

                vendor = "other"
                if any(k in low for k in ("intel", "arc", "battlemage", "iris", "uhd", "xe")):
                    vendor = "intel"
                elif any(k in low for k in ("nvidia", "geforce", "quadro", "rtx", "gtx", "tesla")):
                    vendor = "nvidia"
                elif any(k in low for k in ("amd", "radeon", "ati")):
                    vendor = "amd"

                driver, _ = winreg.QueryValueEx(sub, "DriverVersion")
                vram_bytes = 0
                for vram_key in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                    try:
                        v, _ = winreg.QueryValueEx(sub, vram_key)
                        if v and int(v) > 0:
                            vram_bytes = int(v)
                            break
                    except FileNotFoundError:
                        pass

                adapters.append({
                    "sub_id": sub_name,
                    "name": desc,
                    "vendor": vendor,
                    "driver_version": driver,
                    "memory_total_bytes": vram_bytes,
                })
            except FileNotFoundError:
                pass
    except Exception:
        pass
    return adapters


def _query_linux_drm_gpus() -> list[dict[str, Any]]:
    """Reads Linux DRM subsystem /sys/class/drm/card* (Intel Battlemage/Arc, AMD, NVIDIA)."""
    gpus = []
    drm_dir = "/sys/class/drm"
    if not os.path.exists(drm_dir):
        return gpus

    try:
        cards = [c for c in os.listdir(drm_dir) if re.match(r"^card\d+$", c)]
        for c in sorted(cards):
            card_path = os.path.join(drm_dir, c)
            dev_path = os.path.join(card_path, "device")
            if not os.path.exists(dev_path):
                continue

            vendor_file = os.path.join(dev_path, "vendor")
            vendor = "other"
            if os.path.exists(vendor_file):
                try:
                    with open(vendor_file, "r") as f:
                        v_hex = f.read().strip().lower()
                    if "0x8086" in v_hex:
                        vendor = "intel"
                    elif "0x10de" in v_hex:
                        vendor = "nvidia"
                    elif "0x1002" in v_hex:
                        vendor = "amd"
                except Exception:
                    pass

            gpu_util = 0.0
            busy_file = os.path.join(dev_path, "gpu_busy_percent")
            if os.path.exists(busy_file):
                try:
                    with open(busy_file, "r") as f:
                        gpu_util = float(f.read().strip())
                except Exception:
                    pass

            # Intel GPU Frequency
            freq_mhz = None
            for f_cand in (
                os.path.join(card_path, "gt/gt0/act_freq_mhz"),
                os.path.join(card_path, "gt/gt0/rps_act_freq_mhz"),
                os.path.join(card_path, "gt_act_freq_mhz"),
            ):
                if os.path.exists(f_cand):
                    try:
                        with open(f_cand, "r") as f:
                            freq_mhz = float(f.read().strip())
                        break
                    except Exception:
                        pass

            # Temperature & Power from hwmon
            temp_c = None
            power_w = None
            hwmon_dir = os.path.join(dev_path, "hwmon")
            if os.path.exists(hwmon_dir):
                try:
                    for h in os.listdir(hwmon_dir):
                        h_path = os.path.join(hwmon_dir, h)
                        t_file = os.path.join(h_path, "temp1_input")
                        if os.path.exists(t_file):
                            with open(t_file, "r") as f:
                                temp_c = round(float(f.read().strip()) / 1000.0, 1)
                        p_file = os.path.join(h_path, "power1_input")
                        if os.path.exists(p_file):
                            with open(p_file, "r") as f:
                                power_w = round(float(f.read().strip()) / 1000000.0, 1)
                except Exception:
                    pass

            vendor_names = {
                "intel": f"Intel Graphics ({c})",
                "amd": f"AMD Radeon ({c})",
                "nvidia": f"NVIDIA GPU ({c})",
                "other": f"GPU ({c})",
            }

            gpus.append({
                "id": f"drm-{c}",
                "name": vendor_names.get(vendor, f"GPU ({c})"),
                "vendor": vendor,
                "driver_version": "Linux DRM Kernel",
                "utilization_gpu_percent": round(gpu_util, 1),
                "memory_percent": 0.0,
                "memory_total_bytes": 0,
                "memory_used_bytes": 0,
                "temperature_c": temp_c,
                "power_watts": power_w,
                "freq_mhz": freq_mhz,
                "source": "linux_drm",
            })
    except Exception:
        pass
    return gpus


def get_gpu_stats() -> list[dict[str, Any]]:
    """Gathers GPU telemetry across Intel, AMD, and NVIDIA hardware."""
    all_gpus: list[dict[str, Any]] = []

    # 1. NVIDIA via nvidia-smi (fastest and richest for NVIDIA)
    nv_gpus = _query_nvidia_smi()
    nv_names = {g["name"].lower() for g in nv_gpus}
    all_gpus.extend(nv_gpus)

    # 2. Windows Adapters (Intel Battlemage, Intel Arc, AMD, and NVIDIA)
    if platform.system() == "Windows":
        threading.Thread(target=_update_windows_gpu_perf_cache, daemon=True).start()
        win_adapters = _get_windows_adapters()
        p_util = _win_gpu_perf_cache.get("util", {})
        p_vram = _win_gpu_perf_cache.get("vram", {})

        for a in win_adapters:
            # Skip if already reported with high fidelity by nvidia-smi
            if a["vendor"] == "nvidia" and any(nv in a["name"].lower() for nv in nv_names):
                continue

            vram_tot = a["memory_total_bytes"]
            # Estimate utilization from Windows performance cache if available
            gpu_util = 0.0
            vram_used = 0
            if p_util:
                gpu_util = next(iter(p_util.values()), 0.0)
            if p_vram:
                vram_used = next(iter(p_vram.values()), 0)

            vram_pct = round((vram_used / vram_tot * 100.0), 1) if (vram_tot > 0 and vram_used > 0) else 0.0

            all_gpus.append({
                "id": f"win-gpu-{a['sub_id']}",
                "name": a["name"],
                "vendor": a["vendor"],
                "driver_version": a["driver_version"],
                "utilization_gpu_percent": round(gpu_util, 1),
                "memory_percent": vram_pct,
                "memory_total_bytes": vram_tot,
                "memory_used_bytes": vram_used,
                "temperature_c": None,
                "power_watts": None,
                "source": "windows_adapter",
            })

    # 3. Linux DRM (Intel Battlemage/Arc, AMD, etc.)
    elif platform.system() == "Linux":
        drm_gpus = _query_linux_drm_gpus()
        for dg in drm_gpus:
            if dg["vendor"] == "nvidia" and nv_gpus:
                continue
            all_gpus.append(dg)

    return all_gpus


def get_system_overview() -> dict[str, Any]:
    """Provides cached, non-blocking hardware metrics for the host server."""
    global _stats_cache
    now = time.time()
    with _cache_lock:
        if _stats_cache["data"] and (now - _stats_cache["ts"] < 1.5):
            return _stats_cache["data"]

    cpu_data = get_cpu_stats()
    ram_data = get_ram_stats()
    gpu_data = get_gpu_stats()

    uptime_s = 0.0
    if psutil:
        try:
            uptime_s = round(time.time() - psutil.boot_time(), 0)
        except Exception:
            pass

    overview = {
        "hostname": platform.node() or "Server",
        "os": f"{platform.system()} {platform.release()}",
        "uptime_seconds": uptime_s,
        "cpu": cpu_data,
        "ram": ram_data,
        "gpus": gpu_data,
        "timestamp": now,
    }

    with _cache_lock:
        _stats_cache["ts"] = now
        _stats_cache["data"] = overview

    return overview
