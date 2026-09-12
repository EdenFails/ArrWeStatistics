import os
import re
import asyncio
import httpx
from typing import Any

# Regex to parse active HandBrake / autovideoconverter encoding progress
# Example:
# [autovideoconverter] Encoding /watch/radarr/Spider-Man- Brand New Day 2026.1080p.HQ Pre.Multi.AAC 2.0.x264.mkv: task 1 of 1, 46.60 % (247.73 fps, avg 245.08 fps, ETA 00h07m26s)
ENCODING_REGEX = re.compile(
    r"(?:\[(?P<tag>[^\]]+)\]\s*)?"
    r"Encoding(?:\s+(?P<path>[^:]+?))?:\s+"
    r"task\s+(?P<task_cur>\d+)\s+of\s+(?P<task_tot>\d+),\s+"
    r"(?P<progress>[\d\.]+)\s*%\s*"
    r"\((?:(?P<fps>[\d\.]+)\s*fps,\s*)?"
    r"(?:avg\s+(?P<avg_fps>[\d\.]+)\s*fps,\s*)?"
    r"ETA\s+(?P<eta>[^\)]+)\)",
    re.IGNORECASE,
)

FINISHED_REGEX = re.compile(
    r"(?:\[(?P<tag>[^\]]+)\]\s*)?"
    r"(?:Finished|Completed|Done|Rip done|Converted)(?:\s+encoding|\s+conversion)?(?::|\s+)\s*(?P<detail>.+)",
    re.IGNORECASE,
)

IDLE_KEYWORDS = (
    "watching for files",
    "waiting for files",
    "waiting for new",
    "no files to convert",
    "queue finished",
    "queue is empty",
    "idle",
    "sleeping for",
)


def _format_eta(eta_str: str) -> str:
    """Converts 00h07m26s to 7m 26s or 01h20m05s to 1h 20m."""
    if not eta_str:
        return "Unknown"
    s = eta_str.strip()
    m = re.match(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if m:
        h, mn, sc = m.groups()
        h_val = int(h) if h else 0
        mn_val = int(mn) if mn else 0
        sc_val = int(sc) if sc else 0
        parts = []
        if h_val > 0:
            parts.append(f"{h_val}h")
        if mn_val > 0 or h_val > 0:
            parts.append(f"{mn_val}m")
        if (sc_val > 0 and h_val == 0) or (not parts and sc_val > 0):
            parts.append(f"{sc_val}s")
        if parts:
            return " ".join(parts)
    return s


def _extract_category(path_str: str) -> str:
    """Infers category (radarr, sonarr, movies, tv) from directory path."""
    if not path_str:
        return "general"
    norm = path_str.replace("\\", "/").lower()
    for cat in ("radarr", "sonarr", "anime", "movies", "tv", "series", "music"):
        if f"/{cat}/" in norm or f"/{cat}" in norm:
            return cat
    return "media"


def _clean_title(filename: str) -> str:
    """Removes file extension and cleans up title."""
    base = os.path.basename(filename)
    name, _ = os.path.splitext(base)
    return name


def _read_local_log_tail(filepath: str, max_bytes: int = 65536) -> str:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Log file not found: '{filepath}'. Verify path or container mount.")
    if os.path.isdir(filepath):
        # If user passed directory, check common autovideoconverter log names
        for candidate in ("autovideoconverter.log", "conversion.log", "handbrake.log", "activity.log"):
            sub = os.path.join(filepath, candidate)
            if os.path.isfile(sub):
                filepath = sub
                break
        else:
            raise IsADirectoryError(f"Target is a directory: '{filepath}'. Please specify the exact log file.")

    size = os.path.getsize(filepath)
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        return f.read()


def parse_handbrake_log(log_content: str) -> dict[str, Any]:
    lines = [line.strip() for line in log_content.splitlines() if line.strip()]
    if not lines:
        return {
            "state": "idle",
            "state_label": "IDLE / WAITING",
            "is_encoding": False,
            "current_job": None,
            "recent_completed": [],
            "log_tail": [],
            "stats": {"fps": 0.0, "avg_fps": 0.0, "progress": 0.0},
        }

    current_job = None
    state = "idle"
    state_label = "IDLE"

    # Search from latest lines backward to find current state
    encoding_found = False
    for line in reversed(lines):
        m_enc = ENCODING_REGEX.search(line)
        if m_enc:
            d = m_enc.groupdict()
            file_path = (d.get("path") or "").strip()
            filename = os.path.basename(file_path) if file_path else "Current Stream"
            prog = float(d.get("progress") or 0.0)
            fps = float(d.get("fps") or 0.0)
            avg_fps = float(d.get("avg_fps") or 0.0)
            eta_raw = d.get("eta", "")

            current_job = {
                "file_path": file_path,
                "filename": filename,
                "title": _clean_title(filename),
                "category": _extract_category(file_path),
                "task_current": int(d.get("task_cur") or 1),
                "task_total": int(d.get("task_tot") or 1),
                "progress_percent": prog,
                "fps": fps,
                "avg_fps": avg_fps,
                "eta": eta_raw,
                "eta_formatted": _format_eta(eta_raw),
                "tag": d.get("tag") or "autovideoconverter",
            }
            state = "encoding"
            state_label = f"ENCODING ({prog:.1f}%)"
            encoding_found = True
            break

        # Check if line indicates idle / waiting
        lower = line.lower()
        if any(kw in lower for kw in IDLE_KEYWORDS):
            state = "idle"
            state_label = "IDLE / WAITING"
            break
        if "finished" in lower or "completed" in lower or "rip done" in lower:
            state = "completed"
            state_label = "LAST CONVERSION FINISHED"
            break

    # If encoding was found, verify whether subsequent lines finished it
    if encoding_found and current_job:
        last_line_lower = lines[-1].lower()
        if any(kw in last_line_lower for kw in IDLE_KEYWORDS):
            # It just finished and is now idle
            state = "idle"
            state_label = "IDLE / WAITING"
            current_job = None

    # Find recently completed files in log
    recent_completed = []
    seen_completed = set()
    for line in reversed(lines):
        m_fin = FINISHED_REGEX.search(line)
        if m_fin:
            detail = m_fin.group("detail").strip()
            clean = os.path.basename(detail.split()[0]) if detail else "Completed File"
            if clean not in seen_completed and len(recent_completed) < 8:
                seen_completed.add(clean)
                recent_completed.append({
                    "raw": detail,
                    "filename": clean,
                    "title": _clean_title(clean),
                    "category": _extract_category(detail),
                })

    log_tail = lines[-20:]

    return {
        "state": state,
        "state_label": state_label,
        "is_encoding": state == "encoding",
        "current_job": current_job,
        "recent_completed": recent_completed,
        "log_tail": log_tail,
        "stats": {
            "fps": current_job["fps"] if current_job else 0.0,
            "avg_fps": current_job["avg_fps"] if current_job else 0.0,
            "progress": current_job["progress_percent"] if current_job else 0.0,
            "completed_count": len(recent_completed),
        },
    }


def _clean_docker_multiplexed_stream(data: bytes) -> str:
    """Demultiplexes Docker stdout/stderr 8-byte framed streams into UTF-8 text."""
    lines = []
    i = 0
    n = len(data)
    while i + 8 <= n:
        stream_type = data[i]
        if stream_type in (1, 2) and data[i+1:i+4] == b"\x00\x00\x00":
            frame_len = int.from_bytes(data[i+4:i+8], byteorder="big")
            i += 8
            if i + frame_len <= n:
                payload = data[i:i+frame_len].decode("utf-8", errors="replace")
                lines.append(payload)
                i += frame_len
            else:
                lines.append(data[i:].decode("utf-8", errors="replace"))
                break
        else:
            return data.decode("utf-8", errors="replace")
    return "".join(lines) if lines else data.decode("utf-8", errors="replace")


async def _read_docker_container_logs(container_name: str, tail: int = 100) -> str:
    """Reads logs directly from a Docker container via python docker SDK or /var/run/docker.sock."""
    # 1. Try python docker SDK if installed
    try:
        import docker
        def _get_sync():
            cli = docker.from_env()
            cnt = cli.containers.get(container_name)
            raw = cnt.logs(stdout=True, stderr=True, tail=tail)
            return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        return await asyncio.to_thread(_get_sync)
    except ImportError:
        pass
    except Exception as e:
        if "NotFound" in type(e).__name__ or "404" in str(e):
            raise ValueError(f"Docker container '{container_name}' not found. Verify container name.")

    # 2. Try DOCKER_HOST environment variable if set (e.g. tcp://host.docker.internal:2375)
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host and (docker_host.startswith("tcp://") or docker_host.startswith("http://") or docker_host.startswith("https://")):
        endpoint = docker_host.replace("tcp://", "http://").rstrip("/")
        try:
            url = f"{endpoint}/containers/{container_name}/logs?stdout=1&stderr=1&tail={tail}"
            async with httpx.AsyncClient(timeout=6.0) as d_client:
                res = await d_client.get(url)
                if res.status_code == 200:
                    return _clean_docker_multiplexed_stream(res.content)
                elif res.status_code == 404:
                    raise ValueError(f"Docker container '{container_name}' not found on Docker host {endpoint}.")
                else:
                    raise ValueError(f"Docker host returned HTTP {res.status_code}: {res.text}")
        except ValueError:
            raise
        except Exception as e:
            raise ConnectionError(f"Failed to communicate with DOCKER_HOST at {endpoint}: {e}")

    # 3. Try Unix domain socket /var/run/docker.sock via httpx
    sock_path = "/var/run/docker.sock"
    if os.path.exists(sock_path):
        try:
            transport = httpx.AsyncHTTPTransport(uds=sock_path)
            async with httpx.AsyncClient(transport=transport, timeout=6.0) as d_client:
                url = f"http://docker/containers/{container_name}/logs?stdout=1&stderr=1&tail={tail}"
                res = await d_client.get(url)
                if res.status_code == 200:
                    return _clean_docker_multiplexed_stream(res.content)
                elif res.status_code == 404:
                    raise ValueError(f"Docker container '{container_name}' not found. Verify container name.")
                else:
                    raise ValueError(f"Docker socket returned HTTP {res.status_code}: {res.text}")
        except ValueError:
            raise
        except Exception as e:
            raise ConnectionError(f"Failed to communicate with Docker socket at {sock_path}: {e}")

    raise ValueError(
        f"Docker socket not accessible. Because ArrWeStatistics runs in Docker, you must mount the Docker socket so it can inspect other containers. "
        f"Add '- /var/run/docker.sock:/var/run/docker.sock:ro' to ArrWeStatistics's volumes in your docker-compose.yml."
    )



async def pull_handbrake(client: httpx.AsyncClient, svc: dict) -> dict:
    raw_target = (svc.get("base_url") or "").strip()
    if not raw_target:
        raise ValueError("Docker container name, log path, or HTTP URL is required for HandBrake / AutoVideoConverter.")

    is_http = raw_target.startswith("http://") or raw_target.startswith("https://")
    is_docker = (
        raw_target.startswith("docker:")
        or raw_target.startswith("docker://")
        or (
            not is_http
            and not raw_target.startswith("/")
            and not raw_target.startswith("file://")
            and not (len(raw_target) > 2 and raw_target[1] == ":")
            and not os.path.exists(raw_target)
        )
    )

    log_content = ""

    if is_docker:
        c_name = raw_target
        if c_name.startswith("docker://"):
            c_name = c_name[9:]
        elif c_name.startswith("docker:"):
            c_name = c_name[7:]
        c_name = c_name.strip()
        log_content = await _read_docker_container_logs(c_name)
    elif is_http:
        hdrs = {"User-Agent": "ArrWeStatistics/1.0"}
        key = (svc.get("apikey") or "").strip()
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        resp = await client.get(raw_target, headers=hdrs, timeout=6.0)
        resp.raise_for_status()
        log_content = resp.text
    else:
        # File path
        local_path = raw_target
        if local_path.startswith("file://"):
            local_path = local_path[7:]
            # On Windows, file:///C:/path -> C:/path
            if len(local_path) > 2 and local_path[0] == "/" and local_path[2] == ":":
                local_path = local_path[1:]

        log_content = await asyncio.to_thread(_read_local_log_tail, local_path)

    parsed = parse_handbrake_log(log_content)
    parsed["target"] = raw_target
    parsed["is_http"] = is_http
    parsed["is_docker"] = is_docker
    return parsed

