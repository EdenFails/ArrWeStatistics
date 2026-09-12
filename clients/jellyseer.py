import asyncio
import httpx

_jellyseerr_media_cache: dict[str, dict] = {}


async def pull_jellyseer(client: httpx.AsyncClient, svc: dict) -> dict:
    raw_url = (svc.get("base_url") or "").strip().rstrip("/")
    if raw_url.endswith("/api/v1"):
        url = raw_url[:-7].rstrip("/")
    else:
        url = raw_url

    key = (svc.get("apikey") or "").strip()
    if not key:
        raise ValueError("Jellyseerr API Key is required. Retrieve it from Jellyseerr Settings > General.")

    hdrs = {
        "User-Agent": "ArrWeStatistics/1.0",
        "X-Api-Key": key,
        "Accept": "application/json",
    }

    # 1. Fetch Request Counts
    r_cnt = await client.get(f"{url}/api/v1/request/count", headers=hdrs, timeout=5.0)
    r_cnt.raise_for_status()
    counts = r_cnt.json()

    # 2. Fetch Server Status (version, etc.)
    status_info = {}
    try:
        r_stat = await client.get(f"{url}/api/v1/status", headers=hdrs, timeout=3.0)
        if r_stat.status_code == 200:
            status_info = r_stat.json()
    except Exception:
        pass

    # 3. Fetch Issue Counts
    issue_counts = {}
    try:
        r_iss = await client.get(f"{url}/api/v1/issue/count", headers=hdrs, timeout=3.0)
        if r_iss.status_code == 200:
            issue_counts = r_iss.json()
    except Exception:
        pass

    # 4. Fetch Recent Requests (take 20)
    recent = []
    try:
        r_list = await client.get(
            f"{url}/api/v1/request",
            headers=hdrs,
            params={"take": 20, "skip": 0, "filter": "all", "sort": "added"},
            timeout=5.0,
        )
        if r_list.status_code == 200:
            raw_results = r_list.json().get("results", [])

            status_map = {
                1: "Pending Approval",
                2: "Approved",
                3: "Declined",
                4: "Failed",
                5: "Completed",
            }

            async def _resolve_title(itm: dict) -> tuple[str, str | None]:
                media = itm.get("media", {})
                m_type = itm.get("type", media.get("mediaType", "movie"))
                existing_title = media.get("title") or media.get("name")
                if existing_title:
                    return existing_title, media.get("releaseDate") or media.get("firstAirDate")

                tmdb_id = media.get("tmdbId")
                if not tmdb_id:
                    return f"Request #{itm.get('id')}", None

                cache_key = f"{url}::{m_type}::{tmdb_id}"
                if cache_key in _jellyseerr_media_cache:
                    cached = _jellyseerr_media_cache[cache_key]
                    return cached.get("title", f"Item #{tmdb_id}"), cached.get("release_date")

                try:
                    endpoint = f"{url}/api/v1/{m_type}/{tmdb_id}"
                    r_m = await client.get(endpoint, headers=hdrs, timeout=3.0)
                    if r_m.status_code == 200:
                        m_data = r_m.json()
                        resolved_title = m_data.get("title") or m_data.get("name") or f"{m_type.capitalize()} #{tmdb_id}"
                        rel_date = m_data.get("releaseDate") or m_data.get("firstAirDate")
                        _jellyseerr_media_cache[cache_key] = {
                            "title": resolved_title,
                            "release_date": rel_date,
                        }
                        return resolved_title, rel_date
                except Exception:
                    pass

                fallback = f"{m_type.capitalize()} #{tmdb_id}"
                return fallback, None

            title_results = await asyncio.gather(
                *[_resolve_title(itm) for itm in raw_results],
                return_exceptions=True
            )

            for i, itm in enumerate(raw_results):
                media = itm.get("media", {})
                req_by = itm.get("requestedBy", {})
                m_type = itm.get("type", media.get("mediaType", "movie"))

                t_res = title_results[i] if i < len(title_results) else None
                if isinstance(t_res, tuple):
                    title, rel_date = t_res
                else:
                    title, rel_date = f"Request #{itm.get('id')}", None

                st_code = itm.get("status", 1)
                st_label = status_map.get(st_code, f"Status {st_code}")

                m_st = media.get("status")
                if m_st == 5:
                    st_label = "Available"
                elif m_st == 4:
                    st_label = "Partially Available"
                elif m_st == 3:
                    st_label = "Processing"
                elif st_code == 2:
                    st_label = "Approved"
                elif st_code == 1:
                    st_label = "Pending Approval"
                elif st_code == 3:
                    st_label = "Declined"

                seasons = itm.get("seasons", [])
                seasons_str = None
                if m_type == "tv" and seasons:
                    s_nums = [str(s.get("seasonNumber")) for s in seasons if s.get("seasonNumber") is not None]
                    if s_nums:
                        seasons_str = f"S{', S'.join(s_nums)}" if len(s_nums) <= 4 else f"{len(s_nums)} Seasons"

                year = ""
                if rel_date and len(rel_date) >= 4:
                    year = rel_date[:4]

                recent.append({
                    "id": itm.get("id"),
                    "title": title,
                    "year": year,
                    "media_type": m_type,
                    "seasons": seasons_str,
                    "is_4k": bool(itm.get("is4k", False)),
                    "status": st_label,
                    "status_code": st_code,
                    "media_status": m_st,
                    "requested_by": req_by.get("displayName") or req_by.get("email", "Unknown"),
                    "created_at": itm.get("createdAt"),
                    "updated_at": itm.get("updatedAt"),
                })
    except Exception:
        pass

    return {
        "version": status_info.get("version", "Jellyseerr"),
        "total_requests": counts.get("total", 0),
        "pending_requests": counts.get("pending", 0),
        "approved_requests": counts.get("approved", 0),
        "processing_requests": counts.get("processing", 0),
        "available_requests": counts.get("available", 0),
        "declined_requests": counts.get("declined", 0),
        "movie_requests": counts.get("movie", 0),
        "tv_requests": counts.get("tv", 0),
        "open_issues": issue_counts.get("open", 0),
        "total_issues": issue_counts.get("total", 0),
        "recent_requests": recent,
    }


scrape_jellyseer = pull_jellyseer

