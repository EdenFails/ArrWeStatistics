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
_gpu_energy_cache: dict[str, Any] = {}


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


# Known PCI device IDs mapping: (Marketing Name, Default VRAM Bytes)
_DRM_PCI_DEVICE_MAP: dict[str, tuple[str, int]] = {
    # Intel Battlemage (Xe2)
    "0xe202": ("Intel Arc B580 Graphics", 12 * 1024**3),
    "0xe20b": ("Intel Arc B580 Graphics", 12 * 1024**3),
    "0xe212": ("Intel Arc B580 Graphics", 12 * 1024**3),
    "0xe20c": ("Intel Arc B570 Graphics", 10 * 1024**3),
    "0xe200": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe201": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe203": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe20d": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe20e": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe20f": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe210": ("Intel Arc Battlemage Graphics", 12 * 1024**3),
    "0xe211": ("Intel Arc Battlemage Graphics", 12 * 1024**3),

    # Intel Alchemist (DG2 / Xe-HPG)
    "0x56a0": ("Intel Arc A770 Graphics", 16 * 1024**3),
    "0x56a1": ("Intel Arc A750 Graphics", 8 * 1024**3),
    "0x56a2": ("Intel Arc A580 Graphics", 8 * 1024**3),
    "0x56a5": ("Intel Arc A380 Graphics", 6 * 1024**3),
    "0x56a6": ("Intel Arc A310 Graphics", 4 * 1024**3),
    "0x5690": ("Intel Arc A770M Graphics", 16 * 1024**3),
    "0x5691": ("Intel Arc A730M Graphics", 12 * 1024**3),
    "0x5692": ("Intel Arc A550M Graphics", 8 * 1024**3),
    "0x5693": ("Intel Arc A370M Graphics", 4 * 1024**3),
    "0x5694": ("Intel Arc A350M Graphics", 4 * 1024**3),
    "0x5695": ("Intel Arc A570M Graphics", 8 * 1024**3),
    "0x5696": ("Intel Arc A530M Graphics", 4 * 1024**3),
    "0x56b0": ("Intel Data Center GPU Flex 140", 12 * 1024**3),
    "0x56b1": ("Intel Data Center GPU Flex 170", 16 * 1024**3),
    "0x56b2": ("Intel Arc Pro A40 Graphics", 6 * 1024**3),
    "0x56b3": ("Intel Arc Pro A50 Graphics", 6 * 1024**3),
    "0x56ba": ("Intel Arc Pro A60 Graphics", 12 * 1024**3),
    "0x56bb": ("Intel Arc Pro A30M Graphics", 4 * 1024**3),
    "0x56bc": ("Intel Arc Pro A60M Graphics", 8 * 1024**3),

    # Intel Core Ultra / Lunar Lake / Meteor Lake / Arrow Lake
    "0x6420": ("Intel Arc 140V Graphics", 0),
    "0x64a0": ("Intel Arc 140V Graphics", 0),
    "0x64b0": ("Intel Arc 130V Graphics", 0),
    "0x7d40": ("Intel Arc Graphics", 0),
    "0x7d45": ("Intel Arc Graphics", 0),
    "0x7d55": ("Intel Arc Graphics", 0),
    "0x7d60": ("Intel Arc Graphics", 0),
    "0x7d67": ("Intel Arc Graphics", 0),
    "0x7d51": ("Intel Graphics", 0),
    "0x7d68": ("Intel Graphics", 0),
}


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

            # Detect Kernel Driver
            driver_name = "Linux DRM Kernel"
            drv_base = ""
            driver_link = os.path.join(dev_path, "driver")
            if os.path.exists(driver_link):
                try:
                    drv_base = os.path.basename(os.path.realpath(driver_link)).lower()
                    if drv_base == "xe":
                        driver_name = "Intel Xe Kernel Driver"
                    elif drv_base == "i915":
                        driver_name = "Intel i915 Driver"
                    elif drv_base == "amdgpu":
                        driver_name = "AMD amdgpu Driver"
                    elif drv_base == "nouveau":
                        driver_name = "Nouveau DRM Driver"
                    elif drv_base:
                        driver_name = f"{drv_base.upper()} Driver"
                except Exception:
                    pass

            # Detect GPU Model Name and Default VRAM
            default_vram = 0
            vendor_names = {
                "intel": f"Intel Graphics ({c})",
                "amd": f"AMD Radeon ({c})",
                "nvidia": f"NVIDIA GPU ({c})",
                "other": f"GPU ({c})",
            }
            gpu_name = vendor_names.get(vendor, f"GPU ({c})")

            dev_id_file = os.path.join(dev_path, "device")
            if os.path.exists(dev_id_file):
                try:
                    with open(dev_id_file, "r") as f:
                        d_hex = f.read().strip().lower()
                    if not d_hex.startswith("0x"):
                        d_hex = f"0x{d_hex}"
                    if d_hex in _DRM_PCI_DEVICE_MAP:
                        mapped_name, mapped_vram = _DRM_PCI_DEVICE_MAP[d_hex]
                        gpu_name = mapped_name
                        default_vram = mapped_vram
                except Exception:
                    pass

            # Fallback to lspci if still generic
            if (gpu_name.startswith("Intel Graphics") or gpu_name.startswith("GPU (")) and shutil.which("lspci"):
                try:
                    pci_slot = os.path.basename(os.path.realpath(dev_path))
                    p = subprocess.run(["lspci", "-s", pci_slot], capture_output=True, text=True, timeout=1.0)
                    if p.returncode == 0 and p.stdout.strip():
                        m = re.search(r":\s*(?:Intel Corporation|Advanced Micro Devices|NVIDIA Corporation)?\s*(.*?)(?:\(rev|\n|$)", p.stdout)
                        if m and m.group(1).strip():
                            clean_name = m.group(1).strip()
                            bracket = re.search(r"\[(.*?)\]", clean_name)
                            if bracket:
                                clean_name = bracket.group(1).strip()
                            if "intel" not in clean_name.lower() and vendor == "intel":
                                clean_name = f"Intel {clean_name}"
                            gpu_name = clean_name
                except Exception:
                    pass

            # GPU Core Utilization
            gpu_util = 0.0
            for busy_cand in (
                os.path.join(dev_path, "gpu_busy_percent"),
                os.path.join(card_path, "device/tile0/gt0/busy_percent"),
                os.path.join(card_path, "gt/gt0/busy_percent"),
                os.path.join(card_path, "device/gpu_busy_percent"),
            ):
                if os.path.exists(busy_cand):
                    try:
                        with open(busy_cand, "r") as f:
                            gpu_util = float(f.read().strip())
                        break
                    except Exception:
                        pass

            # GPU Frequency
            freq_mhz = None
            direct_freq_cands = (
                os.path.join(card_path, "device/tile0/gt0/freq0/act_freq"),
                os.path.join(card_path, "device/tile0/gt0/freq0/cur_freq"),
                os.path.join(card_path, "device/tile0/gt0/act_freq_mhz"),
                os.path.join(card_path, "device/tile0/gt0/freq_act"),
                os.path.join(card_path, "device/tile0/gt0/freq_cur"),
                os.path.join(card_path, "device/tile0/gt1/freq0/act_freq"),
                os.path.join(card_path, "device/tile0/gt1/freq0/cur_freq"),
                os.path.join(card_path, "gt/gt0/act_freq_mhz"),
                os.path.join(card_path, "gt/gt0/rps_act_freq_mhz"),
                os.path.join(card_path, "gt_act_freq_mhz"),
                os.path.join(dev_path, "pp_dpm_sclk"),
            )
            for f_cand in direct_freq_cands:
                if os.path.exists(f_cand):
                    try:
                        with open(f_cand, "r") as f:
                            content = f.read().strip()
                        if f_cand.endswith("pp_dpm_sclk"):
                            for line in content.splitlines():
                                if "*" in line:
                                    m_mhz = re.search(r"(\d+)\s*mhz", line, re.IGNORECASE)
                                    if m_mhz:
                                        freq_mhz = float(m_mhz.group(1))
                                        break
                        else:
                            raw_freq = float(content)
                            if raw_freq > 1000000:
                                freq_mhz = round(raw_freq / 1000000.0, 1)
                            elif raw_freq > 10000:
                                freq_mhz = round(raw_freq / 1000.0, 1)
                            elif raw_freq > 0:
                                freq_mhz = round(raw_freq, 1)
                        if freq_mhz and freq_mhz > 0:
                            break
                    except Exception:
                        pass

            # Deep search across all tile/gt/freq sysfs directories if still missing
            if freq_mhz is None:
                for search_base in (os.path.join(card_path, "device"), card_path):
                    if freq_mhz is not None or not os.path.exists(search_base):
                        break
                    try:
                        for root, dirs, files in os.walk(search_base):
                            if os.path.relpath(root, search_base).count(os.sep) > 3:
                                continue
                            for target_name in ("act_freq", "cur_freq", "actual_freq", "act_freq_mhz"):
                                if target_name in files:
                                    try:
                                        with open(os.path.join(root, target_name), "r") as f:
                                            raw_val = float(f.read().strip())
                                        if raw_val > 1000000:
                                            freq_mhz = round(raw_val / 1000000.0, 1)
                                        elif raw_val > 10000:
                                            freq_mhz = round(raw_val / 1000.0, 1)
                                        elif raw_val > 0:
                                            freq_mhz = round(raw_val, 1)
                                        if freq_mhz and freq_mhz > 0:
                                            break
                                    except Exception:
                                        pass
                            if freq_mhz is not None:
                                break
                    except Exception:
                        pass

            # VRAM Detection
            vram_total = 0
            vram_used = 0

            # Priority 1: Known model physical specification (e.g. Arc B580 is 12GB physical GDDR6)
            if default_vram > 0:
                vram_total = default_vram

            vram_tot_cands = (
                os.path.join(card_path, "device/tile0/vram_total_bytes"),
                os.path.join(card_path, "device/tile0/vram0/total_bytes"),
                os.path.join(card_path, "device/lmem_total_bytes"),
                os.path.join(card_path, "lmem_total_bytes"),
                os.path.join(dev_path, "mem_info_vram_total"),
            )
            for f_c in vram_tot_cands:
                if os.path.exists(f_c):
                    try:
                        with open(f_c, "r") as f:
                            raw_tot = int(f.read().strip())
                        if raw_tot > 0:
                            vram_total = raw_tot
                            break
                    except Exception:
                        pass

            vram_used_cands = (
                os.path.join(card_path, "device/tile0/vram_used_bytes"),
                os.path.join(card_path, "device/tile0/vram0/used_bytes"),
                os.path.join(card_path, "device/lmem_used_bytes"),
                os.path.join(card_path, "lmem_used_bytes"),
                os.path.join(dev_path, "mem_info_vram_used"),
            )
            for f_c in vram_used_cands:
                if os.path.exists(f_c):
                    try:
                        with open(f_c, "r") as f:
                            vram_used = int(f.read().strip())
                        if vram_used > 0:
                            break
                    except Exception:
                        pass

            # Check PCI BAR2 aperture if vram_total not found
            if vram_total == 0:
                res_file = os.path.join(dev_path, "resource")
                if os.path.exists(res_file):
                    try:
                        with open(res_file, "r") as f:
                            for line in f:
                                parts = line.strip().split()
                                if len(parts) >= 2:
                                    start = int(parts[0], 16)
                                    end = int(parts[1], 16)
                                    if end > start:
                                        bar_size = end - start + 1
                                        if (2 * 1024**3) <= bar_size <= (64 * 1024**3):
                                            vram_total = max(vram_total, bar_size)
                    except Exception:
                        pass

            vram_pct = round((vram_used / vram_total * 100.0), 1) if (vram_total > 0 and vram_used > 0) else 0.0

            # Temperature & Power from hwmon (local + global /sys/class/hwmon scan)
            temp_c = None
            power_w = None
            hwmon_dirs: list[str] = []

            dev_hwmon = os.path.join(dev_path, "hwmon")
            if os.path.exists(dev_hwmon):
                try:
                    hwmon_dirs.extend([os.path.join(dev_hwmon, h) for h in os.listdir(dev_hwmon)])
                except Exception:
                    pass

            card_hwmon = os.path.join(card_path, "hwmon")
            if os.path.exists(card_hwmon):
                try:
                    hwmon_dirs.extend([os.path.join(card_hwmon, h) for h in os.listdir(card_hwmon)])
                except Exception:
                    pass

            if os.path.exists("/sys/class/hwmon"):
                try:
                    dev_real = os.path.realpath(dev_path)
                    for h in os.listdir("/sys/class/hwmon"):
                        h_path = os.path.join("/sys/class/hwmon", h)
                        if h_path in hwmon_dirs:
                            continue
                        h_dev_link = os.path.join(h_path, "device")
                        if os.path.exists(h_dev_link):
                            try:
                                h_dev_real = os.path.realpath(h_dev_link)
                                if h_dev_real == dev_real or dev_real in h_dev_real or h_dev_real in dev_real:
                                    hwmon_dirs.append(h_path)
                                    continue
                            except Exception:
                                pass
                        name_file = os.path.join(h_path, "name")
                        if os.path.exists(name_file):
                            try:
                                with open(name_file, "r") as f:
                                    h_name = f.read().strip().lower()
                                if h_name in ("xe", "i915", "amdgpu") and (vendor in h_name or drv_base in h_name):
                                    hwmon_dirs.append(h_path)
                            except Exception:
                                pass
                except Exception:
                    pass

            for h_path in hwmon_dirs:
                if temp_c is None:
                    for t_name in ("temp1_input", "temp2_input", "temp3_input"):
                        t_file = os.path.join(h_path, t_name)
                        if os.path.exists(t_file):
                            try:
                                with open(t_file, "r") as f:
                                    raw_t = float(f.read().strip())
                                if raw_t > 0:
                                    temp_c = round(raw_t / 1000.0, 1) if raw_t > 1000 else round(raw_t, 1)
                                    break
                            except Exception:
                                pass

                if power_w is None:
                    for p_name in ("power1_average", "power1_input", "power2_average", "power2_input"):
                        p_file = os.path.join(h_path, p_name)
                        if os.path.exists(p_file):
                            try:
                                with open(p_file, "r") as f:
                                    raw_p = float(f.read().strip())
                                if raw_p > 0:
                                    power_w = round(raw_p / 1000000.0, 1) if raw_p > 10000 else round(raw_p, 1)
                                    break
                            except Exception:
                                pass

                # If instantaneous power is not directly exposed (standard on Xe/Battlemage), compute from energy1_input
                if power_w is None:
                    e_file = os.path.join(h_path, "energy1_input")
                    if os.path.exists(e_file):
                        try:
                            with open(e_file, "r") as f:
                                raw_e = int(f.read().strip())
                            now = time.time()
                            prev = _gpu_energy_cache.get(h_path)
                            if prev and (now - prev["ts"]) >= 0.5:
                                dt = now - prev["ts"]
                                d_energy = raw_e - prev["energy_uj"]
                                if d_energy >= 0:
                                    calc_w = round(d_energy / (dt * 1000000.0), 1)
                                    if 0 <= calc_w <= 600:
                                        power_w = calc_w
                            _gpu_energy_cache[h_path] = {"ts": now, "energy_uj": raw_e}
                        except Exception:
                            pass

            # Fallback to powercap zones if power still unknown
            if power_w is None and os.path.exists("/sys/class/powercap"):
                try:
                    for pz in os.listdir("/sys/class/powercap"):
                        pz_path = os.path.join("/sys/class/powercap", pz)
                        name_f = os.path.join(pz_path, "name")
                        if os.path.exists(name_f):
                            with open(name_f, "r") as f:
                                zname = f.read().strip().lower()
                            if any(k in zname for k in ("gpu", "intel-rapl", "psys")):
                                e_uj_f = os.path.join(pz_path, "energy_uj")
                                if os.path.exists(e_uj_f):
                                    with open(e_uj_f, "r") as f:
                                        raw_e = int(f.read().strip())
                                    now = time.time()
                                    prev = _gpu_energy_cache.get(pz_path)
                                    if prev and (now - prev["ts"]) >= 0.5:
                                        dt = now - prev["ts"]
                                        d_energy = raw_e - prev["energy_uj"]
                                        if d_energy >= 0:
                                            calc_w = round(d_energy / (dt * 1000000.0), 1)
                                            if 0 <= calc_w <= 600:
                                                power_w = calc_w
                                    _gpu_energy_cache[pz_path] = {"ts": now, "energy_uj": raw_e}
                                    if power_w is not None:
                                        break
                except Exception:
                    pass


            gpus.append({
                "id": f"drm-{c}",
                "name": gpu_name,
                "vendor": vendor,
                "driver_version": driver_name,
                "utilization_gpu_percent": round(gpu_util, 1),
                "memory_percent": vram_pct,
                "memory_total_bytes": vram_total,
                "memory_used_bytes": vram_used,
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
