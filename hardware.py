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
import socket
import struct
import ctypes
import json
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
_gpu_util_cache: dict[str, Any] = {}
_gpu_fdinfo_cache: dict[str, Any] = {}


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


def _calc_xe_gt_utilization(card_path: str, dev_path: str) -> float | None:
    """Calculates GPU core utilization from Intel Xe/i915 GT idle residency counter deltas."""
    idle_candidates = [
        os.path.join(card_path, "device/tile0/gt0/gtidle/idle_residency_ms"),
        os.path.join(card_path, "device/gt0/gtidle/idle_residency_ms"),
        os.path.join(card_path, "device/tile0/gt1/gtidle/idle_residency_ms"),
        os.path.join(card_path, "device/gt1/gtidle/idle_residency_ms"),
        os.path.join(card_path, "gt/gt0/rc6_residency_ms"),
        os.path.join(card_path, "power/rc6_residency_ms"),
        os.path.join(dev_path, "tile0/gt0/gtidle/idle_residency_ms"),
        os.path.join(dev_path, "gt0/gtidle/idle_residency_ms"),
        os.path.join(dev_path, "tile0/gt0/rc6_residency_ms"),
    ]

    # Recursive dynamic search if direct candidates not present
    has_candidate = any(os.path.exists(c) for c in idle_candidates)
    if not has_candidate:
        for base_p in (dev_path, card_path):
            if not os.path.exists(base_p):
                continue
            try:
                for root, dirs, files in os.walk(base_p):
                    if os.path.relpath(root, base_p).count(os.sep) > 4:
                        continue
                    for f_name in files:
                        f_low = f_name.lower()
                        if f_low in ("idle_residency_ms", "rc6_residency_ms", "gt_idle_residency_ms") or "idle_residency" in f_low:
                            idle_candidates.append(os.path.join(root, f_name))
            except Exception:
                pass

    for raw_idle_f in idle_candidates:
        idle_f = os.path.normpath(raw_idle_f)
        if os.path.exists(idle_f):
            try:
                with open(idle_f, "r") as f:
                    cur_idle = int(f.read().strip())
                now = time.time()
                prev = _gpu_util_cache.get(idle_f)
                if prev and (now - prev["ts"]) >= 0.3:
                    dt_ms = (now - prev["ts"]) * 1000.0
                    d_idle = cur_idle - prev["idle_ms"]
                    if dt_ms > 0:
                        idle_ratio = max(0.0, min(1.0, d_idle / dt_ms))
                        util = round((1.0 - idle_ratio) * 100.0, 1)
                        _gpu_util_cache[idle_f] = {"ts": now, "idle_ms": cur_idle, "last_util": util}
                        return util
                elif not prev:
                    # First run: take an immediate 40ms mini-sample to establish baseline delta
                    time.sleep(0.04)
                    try:
                        with open(idle_f, "r") as f2:
                            cur2 = int(f2.read().strip())
                        now2 = time.time()
                        dt_ms2 = (now2 - now) * 1000.0
                        d_idle2 = cur2 - cur_idle
                        if dt_ms2 > 0:
                            idle_ratio2 = max(0.0, min(1.0, d_idle2 / dt_ms2))
                            util = round((1.0 - idle_ratio2) * 100.0, 1)
                            _gpu_util_cache[idle_f] = {"ts": now2, "idle_ms": cur2, "last_util": util}
                            return util
                    except Exception:
                        pass
                    _gpu_util_cache[idle_f] = {"ts": now, "idle_ms": cur_idle, "last_util": 0.0}
                elif "last_util" in prev:
                    return prev["last_util"]
            except Exception:
                pass

    # Status check fallback: if gtidle/idle_status is gt-c0 (active)
    status_cands = [
        os.path.join(card_path, "device/tile0/gt0/gtidle/idle_status"),
        os.path.join(card_path, "device/gt0/gtidle/idle_status"),
        os.path.join(dev_path, "tile0/gt0/gtidle/idle_status"),
    ]
    for status_f in status_cands:
        if os.path.exists(status_f):
            try:
                with open(status_f, "r") as f:
                    st = f.read().strip().lower()
                if st == "gt-c0":
                    return 50.0  # actively processing
                elif st == "gt-c6":
                    return 0.0  # sleeping
            except Exception:
                pass

    return None


def _query_drm_direct_memory(card_name: str, driver_type: str = "xe") -> tuple[int, int] | None:
    """Directly queries DRM memory regions via ioctl on /dev/dri/cardX or /dev/dri/renderDX."""
    if platform.system() != "Linux":
        return None

    # Discover candidate device nodes
    candidates = []
    for dri_root in ("/dev/dri", "/host/dev/dri"):
        if not os.path.exists(dri_root):
            continue
        card_node = os.path.join(dri_root, card_name)
        if os.path.exists(card_node):
            candidates.append(card_node)
        m = re.search(r"card(\d+)", card_name)
        if m:
            c_num = int(m.group(1))
            render_node = os.path.join(dri_root, f"renderD{128 + c_num}")
            if os.path.exists(render_node):
                candidates.append(render_node)

        try:
            for node in sorted(os.listdir(dri_root)):
                if node.startswith("renderD"):
                    full_p = os.path.join(dri_root, node)
                    if full_p not in candidates:
                        candidates.append(full_p)
        except Exception:
            pass

    for node_path in candidates:
        if not os.access(node_path, os.R_OK):
            continue

        # Intel Xe Driver Query: DRM_IOCTL_XE_DEVICE_QUERY
        if driver_type == "xe":
            try:
                import fcntl
                fd = None
                for open_flag in (os.O_RDWR, os.O_RDONLY):
                    try:
                        fd = os.open(node_path, open_flag | getattr(os, "O_CLOEXEC", 0))
                        break
                    except Exception:
                        pass
                if fd is None:
                    continue

                try:
                    # DRM_IOCTL_XE_DEVICE_QUERY: 0xc0286440 (_IOWR('d', 0x40, 40))
                    # DRM_XE_DEVICE_QUERY_MEM_REGIONS = 1
                    # struct drm_xe_device_query: extensions(8), query(4), size(4), data(8), reserved(16)
                    q_buf = bytearray(struct.pack("=QIIQQQ", 0, 1, 0, 0, 0, 0))
                    fcntl.ioctl(fd, 0xc0286440, q_buf)
                    _, _, q_size, _, _, _ = struct.unpack("=QIIQQQ", q_buf)
                    if q_size > 0:
                        data_buf = bytearray(q_size)
                        data_addr = ctypes.addressof(ctypes.c_char.from_buffer(data_buf))
                        q_buf2 = bytearray(struct.pack("=QIIQQQ", 0, 1, q_size, data_addr, 0, 0))
                        fcntl.ioctl(fd, 0xc0286440, q_buf2)

                        num_regions, _ = struct.unpack_from("=II", data_buf, 0)
                        offset = 8
                        for _ in range(num_regions):
                            if offset + 88 > len(data_buf):
                                break
                            # struct drm_xe_mem_region: mem_class(H), instance(H), min_page_size(I), total_size(Q), used(Q)...
                            m_class, _, _, tot_sz, used_sz, *_ = struct.unpack_from("=HHIQQQQ6Q", data_buf, offset)
                            offset += 88
                            # DRM_XE_MEM_REGION_CLASS_VRAM == 1
                            if m_class == 1 and tot_sz > 0:
                                return (int(tot_sz), int(used_sz))
                            elif num_regions == 1 and m_class == 0 and tot_sz > 0:
                                return (int(tot_sz), int(used_sz))
                finally:
                    os.close(fd)
            except Exception:
                pass

        # Intel i915 Driver Query: DRM_IOCTL_I915_QUERY
        elif driver_type == "i915":
            try:
                import fcntl
                fd = None
                for open_flag in (os.O_RDWR, os.O_RDONLY):
                    try:
                        fd = os.open(node_path, open_flag | getattr(os, "O_CLOEXEC", 0))
                        break
                    except Exception:
                        pass
                if fd is None:
                    continue

                try:
                    # DRM_IOCTL_I915_QUERY: 0xc0106479 (_IOWR('d', 0x79, 16))
                    # DRM_I915_QUERY_MEMORY_REGIONS = 4
                    # struct drm_i915_query_item: query_id(8), length(4), flags(4), data_ptr(8) -> 24 bytes
                    q_item = bytearray(struct.pack("=QiIQ", 4, 0, 0, 0))
                    item_addr = ctypes.addressof(ctypes.c_char.from_buffer(q_item))
                    # struct drm_i915_query: num_items(4), flags(4), items_ptr(8) -> 16 bytes
                    q_query = bytearray(struct.pack("=IIQ", 1, 0, item_addr))
                    fcntl.ioctl(fd, 0xc0106479, q_query)

                    _, q_len, _, _ = struct.unpack("=QiIQ", q_item)
                    if q_len > 0:
                        data_buf = bytearray(q_len)
                        data_addr = ctypes.addressof(ctypes.c_char.from_buffer(data_buf))
                        q_item2 = bytearray(struct.pack("=QiIQ", 4, q_len, 0, data_addr))
                        item_addr2 = ctypes.addressof(ctypes.c_char.from_buffer(q_item2))
                        q_query2 = bytearray(struct.pack("=IIQ", 1, 0, item_addr2))
                        fcntl.ioctl(fd, 0xc0106479, q_query2)

                        num_regions, *_ = struct.unpack_from("=IIII", data_buf, 0)
                        offset = 16
                        for _ in range(num_regions):
                            if offset + 88 > len(data_buf):
                                break
                            m_class, _, _, probed_sz, unalloc_sz, *_ = struct.unpack_from("=HHIQQ8Q", data_buf, offset)
                            offset += 88
                            # I915_MEMORY_CLASS_DEVICE == 1
                            if m_class == 1 and probed_sz > 0:
                                used_sz = max(0, probed_sz - unalloc_sz)
                                return (int(probed_sz), int(used_sz))
                finally:
                    os.close(fd)
            except Exception:
                pass

    return None


def _query_drm_fdinfo(pci_slot: str, driver_name: str) -> dict[str, Any]:
    """Scans /proc/*/fdinfo/* and /host/proc/*/fdinfo/* for active DRM client memory and engine cycle utilization."""
    res: dict[str, Any] = {"vram_used": 0, "util_pct": None}
    proc_bases = [p for p in ("/host/proc", "/proc") if os.path.exists(p)]
    if not proc_bases:
        return res

    seen_clients: set[tuple[str, str]] = set()
    total_vram_bytes = 0
    active_cycles_sum = 0
    total_cycles_sum = 0

    drv_key = "xe" if "xe" in driver_name.lower() else ("i915" if "i915" in driver_name.lower() else ("amdgpu" if "amd" in driver_name.lower() else ""))

    for proc_root in proc_bases:
        try:
            for pid_entry in os.listdir(proc_root):
                if not pid_entry.isdigit():
                    continue
                fdinfo_dir = os.path.join(proc_root, pid_entry, "fdinfo")
                if not os.path.isdir(fdinfo_dir):
                    continue
                try:
                    for fd_file in os.listdir(fdinfo_dir):
                        fd_path = os.path.join(fdinfo_dir, fd_file)
                        try:
                            with open(fd_path, "r", errors="ignore") as f:
                                lines = f.readlines()
                        except Exception:
                            continue

                        fd_driver = ""
                        fd_pdev = ""
                        fd_client = ""
                        client_vram = 0
                        c_active = 0
                        c_total = 0

                        for line in lines:
                            if ":" not in line:
                                continue
                            k, v = line.split(":", 1)
                            k = k.strip().lower()
                            v = v.strip()

                            if k == "drm-driver":
                                fd_driver = v.lower()
                            elif k == "drm-pdev":
                                fd_pdev = v.lower()
                            elif k == "drm-client-id":
                                fd_client = v
                            elif k in ("drm-resident-vram0", "drm-total-vram0", "drm-resident-vram", "drm-total-vram", "drm-resident-local0", "drm-total-local0"):
                                m_val = re.match(r"(\d+)\s*([a-zA-Z]*)", v)
                                if m_val:
                                    num = int(m_val.group(1))
                                    unit = m_val.group(2).lower()
                                    mult = 1024 if unit in ("kib", "kb", "k") else (1024**2 if unit in ("mib", "mb", "m") else (1024**3 if unit in ("gib", "gb", "g") else 1))
                                    client_vram = max(client_vram, num * mult)
                            elif k.startswith("drm-cycles-") and not k.startswith("drm-total-cycles-"):
                                try:
                                    c_active += int(v.split()[0])
                                except Exception:
                                    pass
                            elif k.startswith("drm-total-cycles-"):
                                try:
                                    c_total += int(v.split()[0])
                                except Exception:
                                    pass

                        if not fd_driver:
                            continue
                        if drv_key and drv_key not in fd_driver:
                            continue
                        if pci_slot and fd_pdev and pci_slot.lower() not in fd_pdev:
                            continue

                        cid_key = (fd_pdev or fd_driver, fd_client or f"{pid_entry}_{fd_file}")
                        if cid_key not in seen_clients:
                            seen_clients.add(cid_key)
                            total_vram_bytes += client_vram
                            active_cycles_sum += c_active
                            total_cycles_sum += c_total
                except Exception:
                    pass
        except Exception:
            pass

    res["vram_used"] = total_vram_bytes

    # Calculate utilization delta from cycles if available
    if active_cycles_sum > 0 and total_cycles_sum > 0:
        now = time.time()
        cache_key = pci_slot or driver_name
        prev = _gpu_fdinfo_cache.get(cache_key)
        if prev and (now - prev["ts"]) >= 0.5:
            d_active = active_cycles_sum - prev["active"]
            d_total = total_cycles_sum - prev["total"]
            if d_total > 0 and d_active >= 0:
                calc_u = round((d_active / d_total) * 100.0, 1)
                res["util_pct"] = max(0.0, min(100.0, calc_u))
                _gpu_fdinfo_cache[cache_key] = {"ts": now, "active": active_cycles_sum, "total": total_cycles_sum, "last_util": res["util_pct"]}
        elif not prev:
            _gpu_fdinfo_cache[cache_key] = {"ts": now, "active": active_cycles_sum, "total": total_cycles_sum, "last_util": None}
        elif "last_util" in prev:
            res["util_pct"] = prev["last_util"]

    return res


def _query_xe_debugfs_vram(card_name: str) -> tuple[int, int] | None:
    """Parses debugfs vram_mm (TTM VRAM Manager) for Intel Xe graphics."""
    m = re.search(r"card(\d+)", card_name)
    minor = m.group(1) if m else "0"
    debugfs_cands = (
        f"/sys/kernel/debug/dri/{minor}/tile0/vram_mm",
        f"/sys/kernel/debug/dri/{minor}/vram_mm",
        f"/sys/kernel/debug/dri/0/tile0/vram_mm",
        f"/sys/kernel/debug/dri/0/vram_mm",
    )
    for dbg_p in debugfs_cands:
        if os.path.exists(dbg_p):
            try:
                vis_avail = None
                vis_size = None
                man_size = None
                with open(dbg_p, "r", errors="ignore") as f:
                    for line in f:
                        line_l = line.strip().lower()
                        if "visible_avail:" in line_l:
                            m_a = re.search(r"(\d+)\s*mib", line_l)
                            if m_a:
                                vis_avail = int(m_a.group(1)) * (1024**2)
                        elif "visible_size:" in line_l:
                            m_s = re.search(r"(\d+)\s*mib", line_l)
                            if m_s:
                                vis_size = int(m_s.group(1)) * (1024**2)
                        elif "man size:" in line_l:
                            m_m = re.search(r"(\d+)", line_l.split(":", 1)[1])
                            if m_m:
                                man_size = int(m_m.group(1))
                if vis_size and vis_avail is not None:
                    used = max(0, vis_size - vis_avail)
                    total = man_size or vis_size
                    return (total, used)
            except Exception:
                pass
    return None


def _query_intel_gpu_top_util() -> float | None:
    """Runs intel_gpu_top once to read instantaneous engine activity."""
    if not shutil.which("intel_gpu_top"):
        return None
    try:
        p = subprocess.run(
            ["intel_gpu_top", "-J", "-s", "100"],
            capture_output=True,
            text=True,
            timeout=0.35,
        )
        if p.returncode == 0 and p.stdout:
            data = json.loads(p.stdout)
            engines = data.get("engines", {})
            max_busy = 0.0
            for eng_info in engines.values():
                busy = eng_info.get("busy", 0.0)
                if isinstance(busy, (int, float)) and busy > max_busy:
                    max_busy = float(busy)
            return round(max_busy, 1)
    except Exception:
        pass
    return None


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
            pci_slot = ""
            try:
                pci_slot = os.path.basename(os.path.realpath(dev_path))
            except Exception:
                pass

            if (gpu_name.startswith("Intel Graphics") or gpu_name.startswith("GPU (")) and shutil.which("lspci") and pci_slot:
                try:
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

            # Intel Xe / i915 GT Idle Residency delta calculation
            if gpu_util == 0.0 and vendor == "intel":
                xe_util = _calc_xe_gt_utilization(card_path, dev_path)
                if xe_util is not None:
                    gpu_util = xe_util

            # Fallback to intel_gpu_top if still 0.0 on Intel
            if gpu_util == 0.0 and vendor == "intel":
                igt_util = _query_intel_gpu_top_util()
                if igt_util is not None:
                    gpu_util = igt_util

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
                                freq_mhz = round(raw_freq / 10000.0, 1)
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

            # Priority 1: Direct DRM Query IOCTL (exact kernel memory allocator stats)
            if drv_base in ("xe", "i915"):
                drm_mem = _query_drm_direct_memory(c, driver_type=drv_base)
                if drm_mem:
                    vram_total, vram_used = drm_mem

            # Priority 2: Known model physical specification (e.g. Arc B580 is 12GB physical GDDR6)
            if default_vram > 0 and vram_total == 0:
                vram_total = default_vram

            # Priority 3: DRM client fdinfo memory and cycle tracking
            if vram_used == 0 or gpu_util == 0.0:
                fdinfo_res = _query_drm_fdinfo(pci_slot, driver_name)
                if vram_used == 0 and fdinfo_res.get("vram_used", 0) > 0:
                    vram_used = fdinfo_res["vram_used"]
                if gpu_util == 0.0 and fdinfo_res.get("util_pct") is not None:
                    gpu_util = fdinfo_res["util_pct"]

            # Priority 4: Debugfs TTM vram_mm
            if vram_used == 0 and drv_base == "xe":
                dbg_mem = _query_xe_debugfs_vram(c)
                if dbg_mem:
                    tot_d, usd_d = dbg_mem
                    if vram_total == 0 and tot_d > 0:
                        vram_total = tot_d
                    if usd_d > 0:
                        vram_used = usd_d

            # Priority 5: Sysfs paths for VRAM total & used (AMD / standard DRM / fallbacks)
            if vram_total == 0:
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

            if vram_used == 0:
                vram_used_cands = (
                    os.path.join(card_path, "device/tile0/vram_used_bytes"),
                    os.path.join(card_path, "device/tile0/vram0/used_bytes"),
                    os.path.join(card_path, "device/tile0/memory/used_bytes"),
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


_net_speed_cache: dict[str, Any] = {
    "ts": 0.0,
    "recv": 0,
    "sent": 0,
    "down_bps": 0.0,
    "up_bps": 0.0,
}
_iface_speed_cache: dict[str, dict[str, Any]] = {}


def _is_virtual_container_iface(name: str) -> bool:
    """Returns True if the network interface is an internal container virtual interface."""
    name_low = name.lower()
    if name_low in ("lo", "docker0") or "loopback" in name_low:
        return True
    if name_low.startswith(("veth", "virbr", "dummy")):
        return True
    # Docker bridge networks are named br-<12 hex chars> e.g. br-0a1b2c3d4e5f
    if name_low.startswith("br-") and len(name_low) >= 6:
        suffix = name_low[3:]
        if all(c in "0123456789abcdef" for c in suffix):
            return True
    return False


def _get_host_ips_from_fib_trie(proc_root: str = "/host/proc") -> list[str]:
    """Extracts host IP addresses from /host/proc/net/fib_trie without executing subprocesses."""
    fib_path = os.path.join(proc_root, "net/fib_trie")
    if not os.path.exists(fib_path):
        return []
    ips: list[str] = []
    try:
        with open(fib_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for i, line in enumerate(lines):
            if "/32 host LOCAL" in line and i > 0:
                prev = lines[i - 1].strip()
                m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", prev)
                if m:
                    ip = m.group(1)
                    if not ip.startswith("127.") and ip not in ips:
                        ips.append(ip)
    except Exception:
        pass
    return ips


def get_network_stats() -> dict[str, Any]:
    """Retrieves host machine network transfer rates and cumulative bandwidth telemetry."""
    global _net_speed_cache, _iface_speed_cache
    now = time.time()

    raw_recv = 0
    raw_sent = 0
    interfaces: list[dict[str, Any]] = []

    # Priority 1: Read host /proc/net/dev if mounted into container (/host/proc/net/dev)
    host_proc_dev = "/host/proc/net/dev"
    if platform.system() == "Linux" and os.path.exists(host_proc_dev):
        try:
            with open(host_proc_dev, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[2:]

            host_ips = _get_host_ips_from_fib_trie("/host/proc")

            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if_name = parts[0].rstrip(":")
                if _is_virtual_container_iface(if_name):
                    continue
                r_bytes = int(parts[1]) if len(parts) > 1 else 0
                s_bytes = int(parts[9]) if len(parts) > 9 else 0
                raw_recv += r_bytes
                raw_sent += s_bytes

                # Determine operstate
                is_up = True
                oper_path = f"/host/sys/class/net/{if_name}/operstate"
                if os.path.exists(oper_path):
                    try:
                        with open(oper_path, "r") as op_f:
                            is_up = (op_f.read().strip().lower() == "up")
                    except Exception:
                        pass
                elif r_bytes == 0 and s_bytes == 0:
                    is_up = False

                # Per-interface speed
                prev_if = _iface_speed_cache.get(if_name, {"ts": 0.0, "recv": r_bytes, "sent": s_bytes, "rx_spd": 0.0, "tx_spd": 0.0})
                if prev_if["ts"] > 0 and (now - prev_if["ts"]) >= 0.5:
                    dt_if = now - prev_if["ts"]
                    rx_spd = max(0.0, round((r_bytes - prev_if["recv"]) / dt_if, 1))
                    tx_spd = max(0.0, round((s_bytes - prev_if["sent"]) / dt_if, 1))
                else:
                    rx_spd = prev_if.get("rx_spd", 0.0)
                    tx_spd = prev_if.get("tx_spd", 0.0)
                _iface_speed_cache[if_name] = {"ts": now, "recv": r_bytes, "sent": s_bytes, "rx_spd": rx_spd, "tx_spd": tx_spd}

                ip_str = host_ips[0] if host_ips and if_name.startswith(("eth", "en", "wl")) else ""
                interfaces.append({
                    "name": if_name,
                    "is_up": is_up,
                    "ip": ip_str,
                    "ips": [ip_str] if ip_str else [],
                    "rx_speed_bytes": rx_spd,
                    "tx_speed_bytes": tx_spd,
                    "rx_bytes": r_bytes,
                    "tx_bytes": s_bytes,
                    "bytes_recv": r_bytes,
                    "bytes_sent": s_bytes,
                })
        except Exception:
            pass

    # Priority 2: Use psutil (native host, Windows, or container in host-network-mode)
    if not interfaces and psutil:
        try:
            per_nic = psutil.net_io_counters(pernic=True)
            addrs = {}
            if_stats = {}
            try:
                if hasattr(psutil, "net_if_addrs"):
                    addrs = psutil.net_if_addrs()
                if hasattr(psutil, "net_if_stats"):
                    if_stats = psutil.net_if_stats()
            except Exception:
                pass

            non_virt_count = sum(1 for ifn in per_nic if not _is_virtual_container_iface(ifn))

            for iface, stats in per_nic.items():
                # Filter virtual container ifaces unless that's all that exists (e.g. isolated bridge container)
                if non_virt_count > 0 and _is_virtual_container_iface(iface):
                    continue
                elif iface.lower() in ("lo", "loopback"):
                    continue

                raw_recv += stats.bytes_recv
                raw_sent += stats.bytes_sent

                ip_str = ""
                all_ips = []
                if iface in addrs:
                    for a in addrs[iface]:
                        if getattr(a, "family", None) in (2, getattr(socket, "AF_INET", 2)):
                            ip_str = a.address
                            all_ips.append(a.address)

                is_up = True
                if iface in if_stats:
                    is_up = getattr(if_stats[iface], "isup", True)

                # Per-interface speed
                prev_if = _iface_speed_cache.get(iface, {"ts": 0.0, "recv": stats.bytes_recv, "sent": stats.bytes_sent, "rx_spd": 0.0, "tx_spd": 0.0})
                if prev_if["ts"] > 0 and (now - prev_if["ts"]) >= 0.5:
                    dt_if = now - prev_if["ts"]
                    rx_spd = max(0.0, round((stats.bytes_recv - prev_if["recv"]) / dt_if, 1))
                    tx_spd = max(0.0, round((stats.bytes_sent - prev_if["sent"]) / dt_if, 1))
                else:
                    rx_spd = prev_if.get("rx_spd", 0.0)
                    tx_spd = prev_if.get("tx_spd", 0.0)
                _iface_speed_cache[iface] = {"ts": now, "recv": stats.bytes_recv, "sent": stats.bytes_sent, "rx_spd": rx_spd, "tx_spd": tx_spd}

                interfaces.append({
                    "name": iface,
                    "is_up": is_up,
                    "ip": ip_str,
                    "ips": all_ips,
                    "rx_speed_bytes": rx_spd,
                    "tx_speed_bytes": tx_spd,
                    "rx_bytes": stats.bytes_recv,
                    "tx_bytes": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "bytes_sent": stats.bytes_sent,
                })
        except Exception:
            pass

    # Priority 3: Fallback to /proc/net/dev on bare Linux if raw_recv is still 0
    if raw_recv == 0 and platform.system() == "Linux" and os.path.exists("/proc/net/dev"):
        try:
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()[2:]
            p_recv = 0
            p_sent = 0
            for line in lines:
                parts = line.strip().split()
                if not parts:
                    continue
                if_name = parts[0].rstrip(":")
                if if_name == "lo":
                    continue
                r_bytes = int(parts[1]) if len(parts) > 1 else 0
                s_bytes = int(parts[9]) if len(parts) > 9 else 0
                p_recv += r_bytes
                p_sent += s_bytes
                if not interfaces:
                    interfaces.append({
                        "name": if_name,
                        "is_up": (r_bytes > 0 or s_bytes > 0),
                        "ip": "",
                        "ips": [],
                        "rx_speed_bytes": 0.0,
                        "tx_speed_bytes": 0.0,
                        "rx_bytes": r_bytes,
                        "tx_bytes": s_bytes,
                        "bytes_recv": r_bytes,
                        "bytes_sent": s_bytes,
                    })
            if p_recv > 0:
                raw_recv = p_recv
                raw_sent = p_sent
        except Exception:
            pass

    down_speed_bps = 0.0
    up_speed_bps = 0.0

    prev_ts = _net_speed_cache["ts"]
    if prev_ts > 0 and (now - prev_ts) >= 0.5:
        dt = now - prev_ts
        d_recv = raw_recv - _net_speed_cache["recv"]
        d_sent = raw_sent - _net_speed_cache["sent"]
        if d_recv >= 0:
            down_speed_bps = round(d_recv / dt, 1)
        if d_sent >= 0:
            up_speed_bps = round(d_sent / dt, 1)
        _net_speed_cache["down_bps"] = down_speed_bps
        _net_speed_cache["up_bps"] = up_speed_bps
    else:
        down_speed_bps = _net_speed_cache.get("down_bps", 0.0)
        up_speed_bps = _net_speed_cache.get("up_bps", 0.0)

    _net_speed_cache["ts"] = now
    _net_speed_cache["recv"] = raw_recv
    _net_speed_cache["sent"] = raw_sent

    try:
        import database as db
        db.update_daily_network_bandwidth(raw_recv, raw_sent)
        full_daily = db.get_daily_network_bandwidth()
    except Exception:
        full_daily = {
            "today_recv_bytes": 0,
            "today_sent_bytes": 0,
            "all_time_recv_bytes": raw_recv,
            "all_time_sent_bytes": raw_sent,
        }

    daily_rx = full_daily.get("today_recv_bytes", 0)
    daily_tx = full_daily.get("today_sent_bytes", 0)
    all_rx = full_daily.get("all_time_recv_bytes", 0)
    all_tx = full_daily.get("all_time_sent_bytes", 0)

    return {
        "download_speed_bytes": down_speed_bps,
        "upload_speed_bytes": up_speed_bps,
        "total_recv_bytes": raw_recv,
        "total_sent_bytes": raw_sent,
        "today_recv_bytes": daily_rx,
        "today_sent_bytes": daily_tx,
        "all_time_recv_bytes": all_rx,
        "all_time_sent_bytes": all_tx,
        "daily": {
            "date": full_daily.get("date"),
            "download_bytes": daily_rx,
            "upload_bytes": daily_tx,
            "total_bytes": daily_rx + daily_tx,
        },
        "all_time": {
            "download_bytes": all_rx,
            "upload_bytes": all_tx,
            "total_bytes": all_rx + all_tx,
        },
        "interfaces": interfaces,
    }


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
    net_data = get_network_stats()

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
        "network": net_data,
        "timestamp": now,
    }

    with _cache_lock:
        _stats_cache["ts"] = now
        _stats_cache["data"] = overview

    return overview

