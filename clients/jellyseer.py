import httpx


async def pull_jellyseer(client: httpx.AsyncClient, svc: dict) -> dict:
    url = svc["base_url"].rstrip("/")
    key = svc.get("apikey") or ""

    hdrs = {
        "User-Agent": "ArrWeStatistics/1.0",
        "X-Api-Key": key,
    }

    r_cnt = await client.get(f"{url}/api/v1/request/count", headers=hdrs, timeout=5.0)
    r_cnt.raise_for_status()
    counts = r_cnt.json()

    recent = []
    try:
        r_list = await client.get(
            f"{url}/api/v1/request",
            headers=hdrs,
            params={"take": 5, "skip": 0, "filter": "all", "sort": "added"},
            timeout=5.0,
        )
        if r_list.status_code == 200:
            status_map = {
                1: "Pending Approval",
                2: "Approved",
                3: "Declined",
            }
            for itm in r_list.json().get("results", []):
                media = itm.get("media", {})
                req_by = itm.get("requestedBy", {})
                m_type = itm.get("type", media.get("mediaType", "unknown"))
                title = media.get("title") or media.get("name") or f"Item #{itm.get('id')}"

                st_code = itm.get("status", 1)
                st_label = status_map.get(st_code, f"Status {st_code}")

                m_st = media.get("status")
                if m_st == 5:
                    st_label = "Available"
                elif m_st == 4:
                    st_label = "Partially Available"
                elif m_st == 3:
                    st_label = "Processing"

                recent.append({
                    "id": itm.get("id"),
                    "title": title,
                    "media_type": m_type,
                    "status": st_label,
                    "requested_by": req_by.get("displayName") or req_by.get("email", "Unknown"),
                    "created_at": itm.get("createdAt"),
                })
    except Exception:
        pass

    return {
        "total_requests": counts.get("total", 0),
        "pending_requests": counts.get("pending", 0),
        "approved_requests": counts.get("approved", 0),
        "processing_requests": counts.get("processing", 0),
        "available_requests": counts.get("available", 0),
        "declined_requests": counts.get("declined", 0),
        "movie_requests": counts.get("movie", 0),
        "tv_requests": counts.get("tv", 0),
        "recent_requests": recent,
    }


scrape_jellyseer = pull_jellyseer
