import time
import asyncio
from typing import Callable, Awaitable
import httpx

from .qbittorrent import pull_qbittorrent
from .sabnzbd import pull_sabnzbd
from .jellyfin import pull_jellyfin
from .jellyseer import pull_jellyseer
from .handbrake import pull_handbrake

ADAPTERS: dict[str, Callable[[httpx.AsyncClient, dict], Awaitable[dict]]] = {
    "qbittorrent": pull_qbittorrent,
    "sabnzbd": pull_sabnzbd,
    "jellyfin": pull_jellyfin,
    "jellyseer": pull_jellyseer,
    "jellyseerr": pull_jellyseer,
    "handbrake": pull_handbrake,
    "autovideoconverter": pull_handbrake,
}


async def fetch_service_data(client: httpx.AsyncClient, svc: dict) -> dict:
    sid = svc.get("id", 0)
    name = svc.get("name", "Unknown")
    stype = (svc.get("service_type") or "").lower()

    fn = ADAPTERS.get(stype)
    if not fn:
        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "error",
            "response_time_ms": 0,
            "error_message": f"Unsupported service: {stype}",
            "data": {},
        }

    t0 = time.perf_counter()
    try:
        data = await asyncio.wait_for(fn(client, svc), timeout=4.0)
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "online",
            "response_time_ms": ms,
            "error_message": None,
            "data": data,
        }
    except httpx.ConnectError:
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "offline",
            "response_time_ms": ms,
            "error_message": "Connection refused",
            "data": {},
        }
    except (httpx.TimeoutException, asyncio.TimeoutError):
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "offline",
            "response_time_ms": ms,
            "error_message": "Connection timed out",
            "data": {},
        }
    except httpx.HTTPStatusError as e:
        ms = int((time.perf_counter() - t0) * 1000)
        code = e.response.status_code
        err_msg = f"HTTP {code}"

        server_detail = ""
        try:
            body = e.response.json()
            if isinstance(body, dict):
                server_detail = body.get("message") or body.get("error") or body.get("detail") or ""
            elif isinstance(body, str):
                server_detail = body
        except Exception:
            txt = e.response.text.strip()
            if txt and len(txt) < 150 and not txt.startswith("<"):
                server_detail = txt

        if code in (401, 403):
            if stype == "jellyfin":
                err_msg = f"Jellyfin returned HTTP {code}: Invalid API key or credentials. Generate an API Key in Jellyfin Dashboard > Advanced > API Keys, or enter Username & Password."
            elif stype == "sabnzbd":
                err_msg = f"SABnzbd returned HTTP {code}: Invalid API Key. Check Config > General in SABnzbd."
            elif stype == "qbittorrent":
                err_msg = f"qBittorrent returned HTTP {code}: Invalid Username or Password."
            elif stype in ("jellyseer", "jellyseerr"):
                err_msg = f"Jellyseerr returned HTTP {code}: Invalid API Key. Check Settings > General in Jellyseerr."
        elif code == 400:
            if stype in ("jellyseer", "jellyseerr"):
                extra = f": {server_detail}" if server_detail else ""
                err_msg = f"Jellyseerr returned HTTP 400 (Bad Request){extra}. Ensure Base URL is formatted as http://HOST:PORT (e.g. http://192.168.1.50:5055) without /api/v1."
            elif server_detail:
                err_msg = f"HTTP {code}: {server_detail}"
        elif server_detail:
            err_msg = f"HTTP {code}: {server_detail}"

        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "error",
            "response_time_ms": ms,
            "error_message": err_msg,
            "data": {},
        }
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "service_id": sid,
            "name": name,
            "service_type": stype,
            "status": "error",
            "response_time_ms": ms,
            "error_message": str(e) or "Fetch failed",
            "data": {},
        }


async def fetch_all_services(client: httpx.AsyncClient, svc_list: list[dict]) -> list[dict]:
    if not svc_list:
        return []
    tasks = [fetch_service_data(client, s) for s in svc_list]
    res = await asyncio.gather(*tasks, return_exceptions=False)
    return list(res)


CLIENT_REGISTRY = ADAPTERS
scrape_service = fetch_service_data
poll_all_services_concurrently = fetch_all_services
