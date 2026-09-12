import os
import time
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, ValidationInfo
import httpx
import json

import database as db
import auth
import storage
from clients import fetch_all_services, fetch_service_data

CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "10"))
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WebInterface")

http_pool: httpx.AsyncClient | None = None
telemetry_cache: dict = {"ts": 0.0, "items": []}
login_tracker: dict[str, list[float]] = {}


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global http_pool
    db.init_db()
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)
    timeouts = httpx.Timeout(connect=5.0, read=6.0, write=5.0, pool=5.0)
    http_pool = httpx.AsyncClient(limits=limits, timeout=timeouts, follow_redirects=True)
    yield
    if http_pool:
        await http_pool.aclose()


app = FastAPI(
    title="ArrWeStatistics",
    version="1.0.0",
    lifespan=app_lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(req: Request, call_next):
    res = await call_next(req)
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    res.headers["Permissions-Policy"] = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )
    res.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "connect-src 'self'"
    )
    if req.url.path.startswith("/static/") or req.url.path == "/":
        res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        res.headers["Pragma"] = "no-cache"
        res.headers["Expires"] = "0"
    return res


class SetupPayload(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class LoginPayload(BaseModel):
    password: str = Field(..., max_length=128)


class PasswordChangePayload(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class ServiceInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    service_type: str = Field(..., max_length=32)
    base_url: str = Field(..., max_length=255)
    apikey: str | None = Field(None, max_length=255)
    username: str | None = Field(None, max_length=128)
    password: str | None = Field(None, max_length=255)
    is_enabled: int = Field(1, ge=0, le=1)
    display_order: int = Field(0, ge=0, le=9999)
    config_json: str | None = Field(None, max_length=4096)

    @field_validator("service_type")
    @classmethod
    def check_type(cls, val: str) -> str:
        s = val.strip().lower()
        valid = {"qbittorrent", "sabnzbd", "jellyfin", "jellyseer", "jellyseerr", "handbrake", "autovideoconverter"}
        if s not in valid:
            raise ValueError(f"service_type must be in {valid}")
        return s

    @field_validator("base_url")
    @classmethod
    def check_url(cls, val: str, info: ValidationInfo) -> str:
        s = val.strip()
        stype = (info.data.get("service_type") or "").strip().lower() if info.data else ""
        if stype in ("handbrake", "autovideoconverter"):
            if s.startswith("http://") or s.startswith("https://") or s.startswith("file://") or s.startswith("/") or s.startswith("\\") or (len(s) > 2 and s[1] == ":" and (s[2] == "\\" or s[2] == "/")):
                return s.rstrip("/") if (s.startswith("http://") or s.startswith("https://")) else s
            raise ValueError("For HandBrake, base_url must be an absolute log file path or HTTP(S) URL")

        if not re.match(r"^https?://[a-zA-Z0-9\.\-_:]+(/[a-zA-Z0-9\.\-_]*)*$", s):
            raise ValueError("base_url must be a valid HTTP or HTTPS URL")
        return s.rstrip("/")

    @field_validator("name")
    @classmethod
    def check_name(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ValueError("Name cannot be empty")
        return re.sub(r"[<>]", "", s)


class PreferenceInput(BaseModel):
    preference_key: str = Field(..., min_length=1, max_length=64)
    preference_val: str = Field(..., max_length=8192)

    @field_validator("preference_key")
    @classmethod
    def check_key(cls, val: str) -> str:
        s = val.strip()
        if not re.match(r"^[a-zA-Z0-9_\.\-]+$", s):
            raise ValueError("Invalid characters in preference_key")
        return s


class StorageInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    mount_path: str = Field(..., min_length=1, max_length=512)
    display_order: int = Field(0, ge=0, le=9999)
    is_enabled: int = Field(1, ge=0, le=1)
    folders: list[str] | None = None

    @field_validator("name")
    @classmethod
    def check_storage_name(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ValueError("Storage name cannot be empty")
        return re.sub(r"[<>]", "", s)

    @field_validator("mount_path")
    @classmethod
    def check_path(cls, val: str) -> str:
        s = val.strip()
        if not s:
            raise ValueError("Mount path cannot be empty")
        return s


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "ArrWeStatistics",
        "version": "1.0.0",
        "read_only": True,
    }


@app.get("/api/auth/status")
async def auth_status(req: Request):
    is_init = db.has_auth()
    tok = auth.pull_token(req)
    is_auth = auth.is_session_valid(tok)
    return {
        "is_initialized": is_init,
        "is_authenticated": is_auth,
    }


@app.post("/api/auth/setup")
async def setup_admin(body: SetupPayload, res: Response):
    if db.has_auth():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System is already initialized. Please log in.",
        )
    h = auth.hash_pw(body.password)
    db.set_initial_auth(h)
    tok = auth.new_session()
    res.set_cookie(
        key="session_token",
        value=tok,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=auth.SESSION_LIFETIME,
    )
    return {
        "success": True,
        "message": "Administrator account provisioned successfully",
        "token": tok,
    }


@app.post("/api/auth/login")
async def login(body: LoginPayload, req: Request, res: Response):
    ip = req.client.host if req.client else "unknown"
    now = time.time()

    fails = [t for t in login_tracker.get(ip, []) if now - t < 60.0]
    login_tracker[ip] = fails

    if len(fails) >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please wait 60 seconds.",
        )

    row = db.read_auth()
    if not row or row["is_initialized"] == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System has not been initialized. Run setup first.",
        )

    if not auth.check_pw(body.password, row["password_hash"]):
        login_tracker.setdefault(ip, []).append(now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    login_tracker.pop(ip, None)
    tok = auth.new_session()
    res.set_cookie(
        key="session_token",
        value=tok,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=auth.SESSION_LIFETIME,
    )
    return {
        "success": True,
        "message": "Authentication successful",
        "token": tok,
    }


@app.post("/api/auth/logout")
async def logout(req: Request, res: Response, _: bool = Depends(auth.require_auth)):
    tok = auth.pull_token(req)
    auth.end_session(tok)
    res.delete_cookie("session_token")
    return {"success": True, "message": "Logged out successfully"}


@app.post("/api/auth/change-password")
async def change_pw(body: PasswordChangePayload, _: bool = Depends(auth.require_auth)):
    row = db.read_auth()
    if not row or not auth.check_pw(body.current_password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password verification failed",
        )
    h = auth.hash_pw(body.new_password)
    db.set_auth_pw(h)
    return {"success": True, "message": "Password updated successfully"}


@app.get("/api/services")
async def get_services(_: bool = Depends(auth.require_auth)):
    return db.fetch_services(include_secrets=False)


@app.post("/api/services", status_code=status.HTTP_201_CREATED)
async def create_service(body: ServiceInput, _: bool = Depends(auth.require_auth)):
    sid = db.insert_service(
        name=body.name,
        service_type=body.service_type,
        base_url=body.base_url,
        apikey=body.apikey,
        username=body.username,
        password=body.password,
        is_enabled=body.is_enabled,
        display_order=body.display_order,
        config_json=body.config_json,
    )
    return db.fetch_service_by_id(sid, include_secrets=False)


@app.get("/api/services/{service_id}")
async def get_single_service(service_id: int, _: bool = Depends(auth.require_auth)):
    svc = db.fetch_service_by_id(service_id, include_secrets=False)
    if not svc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return svc


@app.put("/api/services/{service_id}")
async def edit_service(service_id: int, body: ServiceInput, _: bool = Depends(auth.require_auth)):
    ok = db.modify_service(
        sid=service_id,
        name=body.name,
        service_type=body.service_type,
        base_url=body.base_url,
        apikey=body.apikey,
        username=body.username,
        password=body.password,
        is_enabled=body.is_enabled,
        display_order=body.display_order,
        config_json=body.config_json,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return db.fetch_service_by_id(service_id, include_secrets=False)


@app.delete("/api/services/{service_id}")
async def delete_single_service(service_id: int, _: bool = Depends(auth.require_auth)):
    ok = db.remove_service(service_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return {"success": True, "message": "Service deleted successfully"}


@app.post("/api/services/{service_id}/test")
async def test_service(service_id: int, _: bool = Depends(auth.require_auth)):
    global http_pool
    svc = db.fetch_service_by_id(service_id, include_secrets=True)
    if not svc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    if not http_pool:
        raise HTTPException(status_code=500, detail="HTTP client unavailable")
    return await fetch_service_data(http_pool, svc)


@app.post("/api/services/test-config")
async def test_service_config(body: ServiceInput, _: bool = Depends(auth.require_auth)):
    global http_pool
    if not http_pool:
        raise HTTPException(status_code=500, detail="HTTP client unavailable")
    return await fetch_service_data(http_pool, body.model_dump())


@app.get("/api/telemetry")
@app.get("/api/poll")
async def poll_telemetry(
    force: bool = Query(False),
    _: bool = Depends(auth.require_auth),
):
    global http_pool, telemetry_cache
    if not http_pool:
        raise HTTPException(status_code=500, detail="HTTP client unavailable")

    now = time.time()
    if not force and (now - telemetry_cache["ts"] < CACHE_TTL):
        return {
            "cached": True,
            "cache_age_seconds": round(now - telemetry_cache["ts"], 2),
            "telemetry": telemetry_cache["items"],
        }

    all_svcs = db.fetch_services(include_secrets=True)
    active_svcs = [s for s in all_svcs if s.get("is_enabled", 1) == 1]
    res = await fetch_all_services(http_pool, active_svcs)

    for item in res:
        try:
            db.insert_metric(item["service_id"], item["status"], item["response_time_ms"])
        except Exception:
            pass

    try:
        db.purge_old_metrics(keep_per_service=100)
    except Exception:
        pass

    telemetry_cache["ts"] = time.time()
    telemetry_cache["items"] = res

    return {
        "cached": False,
        "cache_age_seconds": 0.0,
        "telemetry": res,
    }


@app.get("/api/metrics/recent")
async def get_recent_metrics(
    limit: int = Query(10, ge=1, le=100), _: bool = Depends(auth.require_auth)
):
    return db.fetch_recent_metrics_grouped(limit_per_service=limit)


@app.get("/api/metrics/{service_id}")
async def get_service_history(
    service_id: int,
    limit: int = Query(50, ge=1, le=200),
    _: bool = Depends(auth.require_auth),
):
    return db.fetch_metrics(sid=service_id, limit=limit)


@app.get("/api/preferences")
async def list_preferences(_: bool = Depends(auth.require_auth)):
    return db.fetch_preferences()


@app.post("/api/preferences")
async def save_preference(body: PreferenceInput, _: bool = Depends(auth.require_auth)):
    db.upsert_preference(body.preference_key, body.preference_val)
    return {"success": True, "key": body.preference_key}


@app.delete("/api/preferences/{key}")
async def delete_preference(key: str, _: bool = Depends(auth.require_auth)):
    ok = db.remove_preference(key)
    if not ok:
        raise HTTPException(status_code=404, detail="Preference key not found")
    return {"success": True, "message": "Preference deleted"}


@app.get("/api/storage")
async def list_storage_mounts(_: bool = Depends(auth.require_auth)):
    return storage.get_all_storage_data()


@app.post("/api/storage", status_code=status.HTTP_201_CREATED)
async def create_storage_mount(body: StorageInput, _: bool = Depends(auth.require_auth)):
    clean_folders = [f.strip() for f in (body.folders or []) if f.strip()]
    folders_json = json.dumps(clean_folders)
    mid = db.insert_storage_mount(
        name=body.name,
        mount_path=body.mount_path,
        display_order=body.display_order,
        is_enabled=body.is_enabled,
        folders_json=folders_json,
    )
    await storage.trigger_mount_scan(mid)
    res = db.fetch_storage_mount_by_id(mid)
    return res


@app.get("/api/storage/{storage_id}")
async def get_single_storage(storage_id: int, _: bool = Depends(auth.require_auth)):
    m = db.fetch_storage_mount_by_id(storage_id)
    if not m:
        raise HTTPException(status_code=404, detail="Storage mount not found")
    return m


@app.put("/api/storage/{storage_id}")
async def update_storage_mount(
    storage_id: int, body: StorageInput, _: bool = Depends(auth.require_auth)
):
    clean_folders = [f.strip() for f in (body.folders or []) if f.strip()]
    folders_json = json.dumps(clean_folders)
    ok = db.modify_storage_mount(
        mid=storage_id,
        name=body.name,
        mount_path=body.mount_path,
        display_order=body.display_order,
        is_enabled=body.is_enabled,
        folders_json=folders_json,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Storage mount not found")
    await storage.trigger_mount_scan(storage_id)
    return db.fetch_storage_mount_by_id(storage_id)


@app.delete("/api/storage/{storage_id}")
async def delete_storage_mount(storage_id: int, _: bool = Depends(auth.require_auth)):
    ok = db.remove_storage_mount(storage_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Storage mount not found")
    return {"success": True, "message": "Storage mount deleted"}


@app.post("/api/storage/{storage_id}/scan")
async def scan_storage_mount(storage_id: int, _: bool = Depends(auth.require_auth)):
    m = db.fetch_storage_mount_by_id(storage_id)
    if not m:
        raise HTTPException(status_code=404, detail="Storage mount not found")
    started = await storage.trigger_mount_scan(storage_id)
    return {"success": True, "started": started}


@app.get("/api/filesystem/browse")
async def browse_filesystem_route(path: str = Query(default=""), _: bool = Depends(auth.require_auth)):
    return storage.browse_filesystem(path)


if os.path.isdir(UI_DIR):
    app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

    @app.get("/")
    async def index_file():
        idx = os.path.join(UI_DIR, "index.html")
        if os.path.isfile(idx):
            return FileResponse(idx)
        return JSONResponse({"message": "ArrWeStatistics online", "health": "/api/health"})


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8478"))
    level = os.getenv("LOG_LEVEL", "info")

    uvicorn.run(
        "Main:app",
        host=host,
        port=port,
        reload=False,
        access_log=True,
        log_level=level,
    )
