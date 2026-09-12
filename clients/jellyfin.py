import httpx


async def pull_jellyfin(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc["base_url"].rstrip("/")
    key = svc.get("apikey") or ""

    hdrs = {
        "User-Agent": "ArrWeStatistics/1.0",
        "X-Emby-Token": key,
    }

    sys_info = {}
    try:
        r_sys = await client.get(f"{url}/System/Info", headers=hdrs, timeout=4.0)
        if r_sys.status_code == 200:
            sys_info = r_sys.json()
    except Exception:
        pass

    r_sess = await client.get(f"{url}/Sessions", headers=hdrs, timeout=5.0)
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
