import httpx


def get_candidate_urls(base_url: str) -> list[str]:
    clean = base_url.rstrip("/")
    if not clean.startswith(("http://", "https://")):
        clean = f"http://{clean}"
    candidates = [clean]
    if "sabnzbd" in clean:
        candidates.append(clean.replace("sabnzbd", "gluetun"))
        candidates.append(clean.replace("sabnzbd", "172.39.0.2"))
    if "localhost" in clean:
        candidates.append(clean.replace("localhost", "gluetun"))
        candidates.append(clean.replace("localhost", "172.39.0.2"))
        candidates.append(clean.replace("localhost", "host.docker.internal"))
        candidates.append(clean.replace("localhost", "172.17.0.1"))
    elif "127.0.0.1" in clean:
        candidates.append(clean.replace("127.0.0.1", "gluetun"))
        candidates.append(clean.replace("127.0.0.1", "172.39.0.2"))
        candidates.append(clean.replace("127.0.0.1", "host.docker.internal"))
        candidates.append(clean.replace("127.0.0.1", "172.17.0.1"))
    return candidates


async def pull_sabnzbd(client: httpx.AsyncClient, svc: dict) -> dict:
    key = svc.get("apikey") or ""
    candidates = get_candidate_urls(svc["base_url"])
    last_err = None
    body = None
    chosen_url = candidates[0]

    for url in candidates:
        chosen_url = url
        endpoint = f"{url}/api"
        try:
            r = await client.get(
                endpoint,
                params={"mode": "queue", "output": "json", "apikey": key},
                timeout=5.0,
            )
            r.raise_for_status()
            body = r.json()
            break
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_err = e
            continue

    if body is None:
        if last_err:
            raise RuntimeError(f"Could not connect to SABnzbd: {last_err}")
        raise RuntimeError("Failed to connect to SABnzbd WebUI")

    if isinstance(body, dict) and body.get("status") is False:
        raise RuntimeError(f"SABnzbd: {body.get('error', 'API error')}")

    q = body.get("queue", {})
    slots = q.get("slots", [])

    jobs = []
    for s in slots[:15]:
        jobs.append({
            "filename": s.get("filename", "Unknown"),
            "percentage": s.get("percentage", "0"),
            "mbleft": s.get("mbleft", "0"),
            "mb": s.get("mb", "0"),
            "timeleft": s.get("timeleft", "0:00:00"),
            "status": s.get("status", "Unknown"),
        })

    speed_kb = 0.0
    try:
        speed_kb = float(q.get("kbpersec", 0))
    except (ValueError, TypeError):
        pass

    stats = {}
    try:
        r_stats = await client.get(
            endpoint,
            params={"mode": "server_stats", "output": "json", "apikey": key},
            timeout=3.0,
        )
        if r_stats.status_code == 200:
            stats = r_stats.json()
    except Exception:
        pass

    return {
        "status": q.get("status", "Idle"),
        "speed_bytes_sec": int(speed_kb * 1024),
        "speed_display": q.get("speed", "0 KB/s"),
        "size_left": q.get("sizeleft", "0 MB"),
        "mb_left": q.get("mbleft", "0"),
        "total_mb": q.get("mb", "0"),
        "time_left": q.get("timeleft", "0:00:00"),
        "queue_count": int(q.get("noofslots_total", len(slots))),
        "paused": bool(q.get("paused", False)),
        "disk_space_free": q.get("diskspace1", "0"),
        "disk_space_total": q.get("diskspacetotal1", "0"),
        "active_jobs": jobs,
        "bandwidth_today": stats.get("day", 0) if isinstance(stats, dict) else 0,
        "bandwidth_month": stats.get("month", 0) if isinstance(stats, dict) else 0,
        "bandwidth_total": stats.get("total", 0) if isinstance(stats, dict) else 0,
    }


scrape_sabnzbd = pull_sabnzbd
