import httpx

_cookie_cache: dict[str, dict] = {}


def get_candidate_urls(base_url: str) -> list[str]:
    clean = base_url.rstrip("/")
    candidates = [clean]
    if "localhost" in clean:
        candidates.append(clean.replace("localhost", "host.docker.internal"))
        candidates.append(clean.replace("localhost", "172.17.0.1"))
    elif "127.0.0.1" in clean:
        candidates.append(clean.replace("127.0.0.1", "host.docker.internal"))
        candidates.append(clean.replace("127.0.0.1", "172.17.0.1"))
    return candidates


async def pull_qbittorrent(client: httpx.AsyncClient, svc: dict) -> dict:
    raw_url = svc["base_url"].rstrip("/")
    user = svc.get("username") or ""
    pwd = svc.get("password") or ""

    candidates = get_candidate_urls(raw_url)
    last_err = None
    payload = None

    for url in candidates:
        key = f"{url}_{user}"
        headers = {
            "User-Agent": "ArrWeStatistics/1.0",
            "Referer": f"{url}/",
            "Origin": url,
        }
        cookies = _cookie_cache.get(key, {})

        if cookies or not user:
            try:
                r_sync = await client.get(
                    f"{url}/api/v2/sync/maindata",
                    headers=headers,
                    cookies=cookies,
                    timeout=4.0,
                )
                if r_sync.status_code == 200:
                    payload = r_sync.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (401, 403):
                    raise
            except (httpx.ConnectError, httpx.TimeoutException) as ce:
                last_err = ce
                continue
            except Exception:
                pass

        if payload is None and user:
            try:
                r_login = await client.post(
                    f"{url}/api/v2/auth/login",
                    data={"username": user, "password": pwd},
                    headers=headers,
                    timeout=4.0,
                )
            except (httpx.ConnectError, httpx.TimeoutException) as ce:
                last_err = ce
                continue

            if r_login.text.strip() == "Fails." or "Fails" in r_login.text:
                raise RuntimeError("qBittorrent login rejected: check username and password")
            if r_login.status_code == 403:
                raise RuntimeError("qBittorrent returned 403 Forbidden (check IP ban or Host header / CSRF settings)")
            if r_login.status_code != 200:
                raise RuntimeError(f"qBittorrent WebUI returned HTTP {r_login.status_code}")

            cookies = dict(r_login.cookies)
            if "SID" not in cookies:
                for header_val in r_login.headers.get_list("set-cookie"):
                    if "SID=" in header_val:
                        sid_val = header_val.split("SID=")[1].split(";")[0].strip()
                        cookies["SID"] = sid_val
                        break

            _cookie_cache[key] = cookies

            r_sync = await client.get(
                f"{url}/api/v2/sync/maindata",
                headers=headers,
                cookies=cookies,
                timeout=4.0,
            )
            r_sync.raise_for_status()
            payload = r_sync.json()

        if payload is not None:
            break

    if payload is None:
        if last_err and ("localhost" in raw_url or "127.0.0.1" in raw_url):
            raise RuntimeError("Connection refused on localhost. In Docker, 'localhost' refers to the container itself. Use http://host.docker.internal:PORT or your server LAN IP (e.g. http://192.168.x.x:PORT).")
        if last_err:
            raise RuntimeError(f"Could not connect to {raw_url}: {last_err}")
        if not user:
            raise RuntimeError("Authentication required: qBittorrent WebUI rejected unauthenticated access. Please provide username and password.")
        raise RuntimeError("Failed to connect or authenticate with qBittorrent WebUI")

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
