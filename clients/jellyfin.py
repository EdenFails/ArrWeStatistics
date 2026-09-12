import asyncio
import httpx

_jellyfin_token_cache: dict[str, str] = {}


async def _get_jellyfin_token(client: httpx.AsyncClient, url: str, svc: dict) -> str:
    key = (svc.get("apikey") or "").strip()
    username = (svc.get("username") or "").strip()
    password = svc.get("password") or ""

    # If an API key was explicitly given, use it
    if key:
        return key

    cache_key = f"{url}::{username}"
    cached = _jellyfin_token_cache.get(cache_key)
    if cached:
        return cached

    # If username is provided, authenticate via /Users/AuthenticateByName
    if username:
        auth_url = f"{url}/Users/AuthenticateByName"
        auth_hdrs = {
            "Content-Type": "application/json",
            "X-Emby-Authorization": 'MediaBrowser Client="ArrWeStatistics", Device="Dashboard", DeviceId="ArrWeStats", Version="1.0.0"',
            "User-Agent": "ArrWeStatistics/1.0",
        }
        try:
            res = await client.post(
                auth_url,
                headers=auth_hdrs,
                json={"Username": username, "Pw": password},
                timeout=5.0,
            )
            if res.status_code == 200:
                token = res.json().get("AccessToken", "")
                if token:
                    _jellyfin_token_cache[cache_key] = token
                    return token
            elif res.status_code == 401:
                raise Exception("Jellyfin login failed (HTTP 401): Incorrect username or password.")
            else:
                raise Exception(f"Jellyfin login failed with HTTP {res.status_code}")
        except httpx.RequestError as req_err:
            raise Exception(f"Failed to connect to Jellyfin at {auth_url}: {req_err}")

    raise Exception(
        "Jellyfin requires authentication: please provide an API Key (Jellyfin Dashboard > Advanced > API Keys) or Username & Password."
    )


async def _fetch_jellyfin_libraries(
    client: httpx.AsyncClient, url: str, hdrs: dict, params: dict
) -> tuple[list[dict], dict]:
    """Fetches libraries and item counts per library, plus global item counts."""
    global_counts: dict[str, int] = {}
    try:
        r_cnt = await client.get(f"{url}/Items/Counts", headers=hdrs, params=params, timeout=3.0)
        if r_cnt.status_code == 200:
            c = r_cnt.json()
            global_counts = {
                "movies": c.get("MovieCount", 0),
                "series": c.get("SeriesCount", 0),
                "episodes": c.get("EpisodeCount", 0),
                "songs": c.get("SongCount", 0),
                "albums": c.get("AlbumCount", 0),
                "artists": c.get("ArtistCount", 0),
                "books": c.get("BookCount", 0),
                "total": c.get("ItemCount", 0),
            }
    except Exception:
        pass

    raw_libs: list[dict] = []
    # 1. Try VirtualFolders
    try:
        r_vf = await client.get(f"{url}/Library/VirtualFolders", headers=hdrs, params=params, timeout=3.0)
        if r_vf.status_code == 200:
            data = r_vf.json()
            if isinstance(data, list):
                raw_libs = data
    except Exception:
        pass

    # 2. Fallback to MediaFolders
    if not raw_libs:
        try:
            r_mf = await client.get(f"{url}/Library/MediaFolders", headers=hdrs, params=params, timeout=3.0)
            if r_mf.status_code == 200:
                data = r_mf.json()
                raw_libs = data.get("Items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            pass

    # 3. Fallback to UserViews
    if not raw_libs:
        try:
            r_uv = await client.get(f"{url}/UserViews", headers=hdrs, params=params, timeout=3.0)
            if r_uv.status_code == 200:
                data = r_uv.json()
                raw_libs = data.get("Items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            pass

    # Deduplicate libraries by ItemId or Id or Name
    seen_ids = set()
    unique_libs = []
    for lib in raw_libs:
        lid = lib.get("ItemId") or lib.get("Id") or lib.get("Name")
        if lid and lid not in seen_ids:
            seen_ids.add(lid)
            unique_libs.append(lib)

    async def _count_library(lib: dict) -> dict:
        name = lib.get("Name") or "Unnamed Library"
        lib_id = lib.get("ItemId") or lib.get("Id") or ""
        col_type = (lib.get("CollectionType") or "mixed").lower()

        if not lib_id:
            return {
                "id": lib_id,
                "name": name,
                "type": col_type,
                "count": 0,
                "sub_count": 0,
                "formatted": "0 items",
            }

        count = 0
        sub_count = 0
        formatted = ""

        try:
            if col_type in ("movies", "movie"):
                p_mov = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "Movie"}
                r_m = await client.get(f"{url}/Items", headers=hdrs, params=p_mov, timeout=3.0)
                if r_m.status_code == 200:
                    count = r_m.json().get("TotalRecordCount", 0)
                if count == 0:
                    p_all = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true"}
                    r_all = await client.get(f"{url}/Items", headers=hdrs, params=p_all, timeout=3.0)
                    if r_all.status_code == 200:
                        count = r_all.json().get("TotalRecordCount", 0)
                formatted = f"{count:,} movies" if count != 1 else "1 movie"

            elif col_type in ("tvshows", "series", "shows"):
                p_series = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "Series"}
                p_ep = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "Episode"}
                r_s, r_e = await asyncio.gather(
                    client.get(f"{url}/Items", headers=hdrs, params=p_series, timeout=3.0),
                    client.get(f"{url}/Items", headers=hdrs, params=p_ep, timeout=3.0),
                    return_exceptions=True,
                )
                if not isinstance(r_s, Exception) and r_s.status_code == 200:
                    count = r_s.json().get("TotalRecordCount", 0)
                if not isinstance(r_e, Exception) and r_e.status_code == 200:
                    sub_count = r_e.json().get("TotalRecordCount", 0)

                if count == 0 and sub_count == 0:
                    p_all = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true"}
                    r_all = await client.get(f"{url}/Items", headers=hdrs, params=p_all, timeout=3.0)
                    if r_all.status_code == 200:
                        count = r_all.json().get("TotalRecordCount", 0)
                    formatted = f"{count:,} items"
                else:
                    ep_str = f" ({sub_count:,} episodes)" if sub_count > 0 else ""
                    formatted = f"{count:,} series{ep_str}"

            elif col_type in ("music",):
                p_alb = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "MusicAlbum"}
                p_trk = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "Audio"}
                r_a, r_t = await asyncio.gather(
                    client.get(f"{url}/Items", headers=hdrs, params=p_alb, timeout=3.0),
                    client.get(f"{url}/Items", headers=hdrs, params=p_trk, timeout=3.0),
                    return_exceptions=True,
                )
                if not isinstance(r_a, Exception) and r_a.status_code == 200:
                    count = r_a.json().get("TotalRecordCount", 0)
                if not isinstance(r_t, Exception) and r_t.status_code == 200:
                    sub_count = r_t.json().get("TotalRecordCount", 0)

                alb_str = f"{count:,} albums" if count != 1 else "1 album"
                trk_str = f" ({sub_count:,} tracks)" if sub_count > 0 else ""
                formatted = f"{alb_str}{trk_str}"

            elif col_type in ("books", "audiobooks"):
                p_bk = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true", "IncludeItemTypes": "Book,Audio"}
                r_b = await client.get(f"{url}/Items", headers=hdrs, params=p_bk, timeout=3.0)
                if r_b.status_code == 200:
                    count = r_b.json().get("TotalRecordCount", 0)
                formatted = f"{count:,} books" if count != 1 else "1 book"

            else:
                p_all = {**params, "ParentId": lib_id, "Recursive": "true", "Limit": "0", "EnableTotalRecordCount": "true"}
                r = await client.get(f"{url}/Items", headers=hdrs, params=p_all, timeout=3.0)
                if r.status_code == 200:
                    count = r.json().get("TotalRecordCount", 0)
                formatted = f"{count:,} items" if count != 1 else "1 item"

        except Exception:
            formatted = f"{count:,} items"

        return {
            "id": lib_id,
            "name": name,
            "type": col_type,
            "count": count,
            "sub_count": sub_count,
            "formatted": formatted,
        }

    if unique_libs:
        results = await asyncio.gather(*[_count_library(lib) for lib in unique_libs], return_exceptions=True)
        libraries = [r for r in results if isinstance(r, dict)]
    else:
        libraries = []

    return libraries, global_counts


async def pull_jellyfin(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc["base_url"].rstrip("/")
    token = await _get_jellyfin_token(client, url, svc)

    hdrs = {
        "User-Agent": "ArrWeStatistics/1.0",
        "Authorization": f'MediaBrowser Client="ArrWeStatistics", Device="Dashboard", DeviceId="ArrWeStats", Version="1.0.0", Token="{token}"',
        "X-Emby-Token": token,
        "X-MediaBrowser-Token": token,
    }
    params = {"api_key": token, "ApiKey": token}

    sys_info = {}
    try:
        r_sys = await client.get(f"{url}/System/Info", headers=hdrs, params=params, timeout=4.0)
        if r_sys.status_code == 200:
            sys_info = r_sys.json()
    except Exception:
        pass

    r_sess = await client.get(f"{url}/Sessions", headers=hdrs, params=params, timeout=5.0)

    # If token was rejected/expired and username/password available, clear cache and retry once
    if r_sess.status_code == 401:
        username = (svc.get("username") or "").strip()
        cache_key = f"{url}::{username}"
        if cache_key in _jellyfin_token_cache:
            del _jellyfin_token_cache[cache_key]
            token = await _get_jellyfin_token(client, url, svc)
            hdrs["X-Emby-Token"] = token
            hdrs["Authorization"] = f'MediaBrowser Client="ArrWeStatistics", Device="Dashboard", DeviceId="ArrWeStats", Version="1.0.0", Token="{token}"'
            params["api_key"] = token
            r_sess = await client.get(f"{url}/Sessions", headers=hdrs, params=params, timeout=5.0)

    if r_sess.status_code == 401:
        raise Exception(
            "Jellyfin returned HTTP 401 Unauthorized: Invalid API Key or credentials. "
            "Please check your API key (generate in Jellyfin Dashboard > Advanced > API Keys) or your Username and Password."
        )

    r_sess.raise_for_status()
    raw = r_sess.json()

    streams = []
    direct_cnt = 0
    trans_cnt = 0
    hw_cnt = 0

    for s in raw:
        item = s.get("NowPlayingItem")
        if not item:
            continue

        play_st = s.get("PlayState", {})
        tx_info = s.get("TranscodingInfo", {})

        is_tx = bool(tx_info)
        is_direct = not is_tx or tx_info.get("IsVideoDirect", False)

        hw = tx_info.get("HardwareAccelerationType")
        has_hw = bool(hw and hw.lower() != "none")

        if is_tx:
            trans_cnt += 1
            if has_hw:
                hw_cnt += 1
        else:
            direct_cnt += 1

        pos = play_st.get("PositionTicks", 0)
        total_ticks = item.get("RunTimeTicks", 1)
        pct = 0.0
        if total_ticks and total_ticks > 0:
            pct = min(100.0, round((pos / total_ticks) * 100, 1))

        m_type = item.get("Type", "Media")
        title = item.get("Name", "Unknown Title")
        series = item.get("SeriesName")
        if series:
            s_idx = item.get("ParentIndexNumber")
            e_idx = item.get("IndexNumber")
            if s_idx is not None and e_idx is not None:
                title = f"{series} S{s_idx:02d}E{e_idx:02d} - {title}"
            else:
                title = f"{series} - {title}"

        streams.append({
            "session_id": s.get("Id", "unknown"),
            "user_name": s.get("UserName", "Unknown User"),
            "client": s.get("Client", "Generic Client"),
            "device_name": s.get("DeviceName", "Unknown Device"),
            "media_title": title,
            "media_type": m_type,
            "is_paused": bool(play_st.get("IsPaused", False)),
            "progress_percent": pct,
            "is_transcoding": is_tx,
            "is_direct_play": is_direct,
            "hardware_acceleration": hw if has_hw else None,
            "transcode_reasons": tx_info.get("TranscodeReasons", []),
            "video_codec": tx_info.get("VideoCodec") or (item.get("MediaStreams", [{}])[0].get("Codec") if item.get("MediaStreams") else None),
            "audio_codec": tx_info.get("AudioCodec"),
        })

    libraries, item_counts = await _fetch_jellyfin_libraries(client, url, hdrs, params)

    return {
        "server_name": sys_info.get("ServerName", "Jellyfin Server"),
        "version": sys_info.get("Version", "Unknown"),
        "operating_system": sys_info.get("OperatingSystem", "Unknown"),
        "active_stream_count": len(streams),
        "direct_play_count": direct_cnt,
        "transcoding_count": trans_cnt,
        "hardware_transcoding_count": hw_cnt,
        "streams": streams,
        "libraries": libraries,
        "item_counts": item_counts,
    }


scrape_jellyfin = pull_jellyfin

