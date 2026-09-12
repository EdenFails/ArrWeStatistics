import httpx

_cookie_cache: dict[str, dict] = {}


async def pull_qbittorrent(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc["base_url"].rstrip("/")
    user = svc.get("username") or ""
    pwd = svc.get("password") or ""
    key = f"{url}_{user}"

    headers = {
        "User-Agent": "ArrWeStatistics/1.0",
        "Referer": url,
    }

    cookies = _cookie_cache.get(key, {})

    payload = None
    if cookies or not user:
        try:
            r_sync = await client.get(
                f"{url}/api/v2/sync/maindata",
                headers=headers,
                cookies=cookies,
                timeout=5.0,
            )
            if r_sync.status_code == 200:
                payload = r_sync.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 403:
                raise
        except Exception:
            pass

    if payload is None and user:
        r_login = await client.post(
            f"{url}/api/v2/auth/login",
            data={"username": user, "password": pwd},
            headers=headers,
            timeout=5.0,
        )
        if r_login.status_code != 200 or "Fails" in r_login.text:
            raise RuntimeError("qBittorrent login rejected")

        cookies = dict(r_login.cookies)
        _cookie_cache[key] = cookies

        r_sync = await client.get(
            f"{url}/api/v2/sync/maindata",
            headers=headers,
            cookies=cookies,
            timeout=5.0,
        )
        r_sync.raise_for_status()
        payload = r_sync.json()

    if payload is None:
        raise RuntimeError("Failed to retrieve qBittorrent maindata")

    state = payload.get("server_state", {})
    torrents = payload.get("torrents", {})

    total = len(torrents)
    dl_count = 0
    up_count = 0
    paused_count = 0
    done_count = 0
    active_count = 0

    active_items = []

    for _, t in torrents.items():
        st = t.get("state", "").lower()
        dl_spd = t.get("dlspeed", 0)
        up_spd = t.get("upspeed", 0)

        if "downloading" in st or "dl" in st:
            dl_count += 1
        if "uploading" in st or "stalledup" in st or "up" in st:
            up_count += 1
        if "paused" in st:
            paused_count += 1
        if t.get("progress", 0) >= 1.0:
            done_count += 1
        if dl_spd > 0 or up_spd > 0:
            active_count += 1

        if (dl_spd > 0 or up_spd > 0) and len(active_items) < 15:
            active_items.append({
                "name": t.get("name", "Unknown"),
                "size": t.get("size", 0),
                "progress": round(t.get("progress", 0) * 100, 1),
                "dlspeed": dl_spd,
                "upspeed": up_spd,
                "eta": t.get("eta", 0),
                "state": st,
            })

    return {
        "dl_speed_bytes": state.get("dl_info_speed", 0),
        "up_speed_bytes": state.get("up_info_speed", 0),
        "dl_total_bytes": state.get("dl_info_data", 0),
        "up_total_bytes": state.get("up_info_data", 0),
        "free_space_bytes": state.get("free_space_on_disk", 0),
        "dht_nodes": state.get("dht_nodes", 0),
        "connection_status": state.get("connection_status", "unknown"),
        "torrents": {
            "total": total,
            "active": active_count,
            "downloading": dl_count,
            "seeding": up_count,
            "paused": paused_count,
            "completed": done_count,
        },
        "active_items": active_items,
    }


scrape_qbittorrent = pull_qbittorrent
