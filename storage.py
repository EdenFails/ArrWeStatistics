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

        total_b = live_disk["total_bytes"] or m["total_bytes"] or 0
        used_b = live_disk["used_bytes"] or m["used_bytes"] or 0
        free_b = live_disk["free_bytes"] or m["free_bytes"] or 0
        used_pct = round((used_b / total_b * 100), 1) if total_b > 0 else 0.0
        is_accessible = live_disk["exists"]
        err = live_disk["error"]

        # If scan hasn't run yet, construct default items for watched folders
        display_folders = []
        if cached_folders:
            display_folders = cached_folders
        else:
            for item in watched_folders:
                fn = item if isinstance(item, str) else item.get("name", "")
                fp = item if isinstance(item, str) else item.get("path", fn)
                display_folders.append({
                    "name": fn,
                    "path": fp,
                    "bytes": 0,
                    "exists": False,
                    "percent_of_used": 0.0,
                })

        results.append({
            "id": mid,
            "name": m["name"],
            "mount_path": base_path,
            "display_order": m["display_order"],
            "is_enabled": m["is_enabled"],
            "is_accessible": is_accessible,
            "exists": is_accessible,
            "error_message": err,
            "error": err,
            "total_bytes": total_b,
            "used_bytes": used_b,
            "free_bytes": free_b,
            "used_percent": used_pct,
            "used_pct": used_pct,
            "last_scanned_ts": m["last_scanned_ts"],
            "is_scanning": is_mount_scanning(mid),
            "watched_folders": watched_folders,
            "folder_breakdown": cached_folders,
            "folders": display_folders,
        })

    return results


def browse_filesystem(target_path: str | None = None) -> dict:
    is_windows = os.name == "nt"

    if not target_path or not str(target_path).strip():
        target_path = "C:\\" if is_windows else "/"

    clean_path = os.path.abspath(target_path)

    if not os.path.exists(clean_path):
        fallback = "C:\\" if is_windows else "/"
        if os.path.exists(fallback):
            clean_path = fallback
        else:
            clean_path = os.path.abspath(".")

    parent_path = os.path.dirname(clean_path)
    if parent_path == clean_path:
        parent_path = None

    directories = []
    error_msg = None

    try:
        with os.scandir(clean_path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=True):
                        if not entry.name.startswith("."):
                            directories.append({
                                "name": entry.name,
                                "path": entry.path.replace("\\", "/") if not is_windows else entry.path,
                            })
                except (PermissionError, OSError):
                    continue
    except (PermissionError, OSError) as e:
        error_msg = f"Cannot read directory: {e}"

    directories.sort(key=lambda d: d["name"].lower())

    display_curr = clean_path.replace("\\", "/") if not is_windows else clean_path
    display_parent = parent_path.replace("\\", "/") if (parent_path and not is_windows) else parent_path

    drives = []
    if is_windows:
        import string
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                drives.append({"name": f"{letter}:", "path": drive})

    return {
        "current_path": display_curr,
        "parent_path": display_parent,
        "directories": directories,
        "drives": drives,
        "error": error_msg,
    }
