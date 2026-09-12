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


async def pull_jellyfin(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc["base_url"].rstrip("/")
    token = await _get_jellyfin_token(client, url, svc)

    hdrs = {
        "User-Agent": "ArrWeStatistics/1.0",
        "X-Emby-Token": token,
        "Authorization": f'MediaBrowser Client="ArrWeStatistics", Device="Dashboard", DeviceId="ArrWeStats", Version="1.0.0", Token="{token}"',
    }
    params = {"api_key": token}

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

    return {
        "server_name": sys_info.get("ServerName", "Jellyfin Server"),
        "version": sys_info.get("Version", "Unknown"),
        "operating_system": sys_info.get("OperatingSystem", "Unknown"),
        "active_stream_count": len(streams),
        "direct_play_count": direct_cnt,
        "transcoding_count": trans_cnt,
        "hardware_transcoding_count": hw_cnt,
        "streams": streams,
    }


scrape_jellyfin = pull_jellyfin
