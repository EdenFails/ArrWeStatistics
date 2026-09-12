import os
import time
import json
import shutil
import asyncio
from concurrent.futures import ThreadPoolExecutor

import database as db

_scanner_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="storage_scan")
_active_scans: set[int] = set()


def get_disk_usage(mount_path: str) -> dict:
    clean = os.path.abspath(mount_path)
    if not os.path.exists(clean):
        return {
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "exists": False,
            "error": f"Path not found: {mount_path}",
        }

    try:
        usage = shutil.disk_usage(clean)
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "exists": True,
            "error": None,
        }
    except Exception as e:
        return {
            "total_bytes": 0,
            "used_bytes": 0,
            "free_bytes": 0,
            "exists": False,
            "error": str(e),
        }


def _calc_folder_size_sync(folder_path: str) -> int:
    total = 0
    if not os.path.exists(folder_path):
        return 0

    try:
        with os.scandir(folder_path) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += _calc_folder_size_sync(entry.path)
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError):
        pass

    return total


def _run_mount_scan_sync(mount_id: int) -> None:
    mount = db.fetch_storage_mount_by_id(mount_id)
    if not mount:
        return

    base_path = mount["mount_path"]
    disk = get_disk_usage(base_path)

    raw_folders = []
    try:
        raw_folders = json.loads(mount.get("folders_json") or "[]")
    except Exception:
        raw_folders = []

    folder_stats = []
    total_folders_bytes = 0

    for item in raw_folders:
        if isinstance(item, str):
            f_name = item.strip()
            f_sub = item.strip()
        elif isinstance(item, dict):
            f_name = item.get("name", "").strip()
            f_sub = item.get("path", "").strip() or f_name
        else:
            continue

        if not f_name:
            continue

        full_path = f_sub if os.path.isabs(f_sub) else os.path.join(base_path, f_sub)
        size = _calc_folder_size_sync(full_path)
        total_folders_bytes += size

        folder_stats.append({
            "name": f_name,
            "path": full_path,
            "size_bytes": size,
            "exists": os.path.exists(full_path),
        })

    now = time.time()
    db.update_storage_stats(
        mid=mount_id,
        total_bytes=disk["total_bytes"],
        used_bytes=disk["used_bytes"],
        free_bytes=disk["free_bytes"],
        cached_folders_json=json.dumps(folder_stats),
        last_scanned_ts=now,
    )


async def trigger_mount_scan(mount_id: int) -> bool:
    global _active_scans
    if mount_id in _active_scans:
        return False

    _active_scans.add(mount_id)

    def _done_callback(fut):
        _active_scans.discard(mount_id)

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(_scanner_pool, _run_mount_scan_sync, mount_id)
    fut.add_done_callback(_done_callback)
    return True


def is_mount_scanning(mount_id: int) -> bool:
    return mount_id in _active_scans


def get_all_storage_data() -> list[dict]:
    mounts = db.fetch_storage_mounts()
    results = []

    for m in mounts:
        if m.get("is_enabled", 1) == 0:
            continue

        mid = m["id"]
        base_path = m["mount_path"]
        live_disk = get_disk_usage(base_path)

        cached_folders = []
        try:
            cached_folders = json.loads(m.get("cached_folders_json") or "[]")
        except Exception:
            pass

        watched_folders = []
        try:
            watched_folders = json.loads(m.get("folders_json") or "[]")
        except Exception:
            pass

        results.append({
            "id": mid,
            "name": m["name"],
            "mount_path": base_path,
            "display_order": m["display_order"],
            "is_enabled": m["is_enabled"],
            "exists": live_disk["exists"],
            "error": live_disk["error"],
            "total_bytes": live_disk["total_bytes"] or m["total_bytes"],
            "used_bytes": live_disk["used_bytes"] or m["used_bytes"],
            "free_bytes": live_disk["free_bytes"] or m["free_bytes"],
            "used_pct": round((live_disk["used_bytes"] / live_disk["total_bytes"] * 100), 1) if live_disk["total_bytes"] > 0 else 0.0,
            "last_scanned_ts": m["last_scanned_ts"],
            "is_scanning": is_mount_scanning(mid),
            "watched_folders": watched_folders,
            "folder_breakdown": cached_folders,
        })

    return results
