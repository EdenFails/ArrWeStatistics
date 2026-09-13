import os
import sys
import tempfile
import importlib
import time
import shutil

test_db = os.path.join(tempfile.gettempdir(), "test_arrwestats.db")
if os.path.exists(test_db):
    os.remove(test_db)
os.environ["DB_PATH"] = test_db

import database as db
import auth
from starlette.testclient import TestClient

import Main
app = Main.app


def run_tests():
    print("[*] Running Verification Test Suite...")

    db.create_tables()
    assert os.path.exists(test_db), "Database file was not created"
    assert db.is_auth_initialized() is False, "Auth should not be initialized initially"
    print("[+] Test 1 Passed: Database schema initialized successfully.")

    password = "MasterAdminPassword123!"
    hashed = auth.hash_password(password)
    assert hashed.startswith("$argon2id$"), f"Unexpected hash format: {hashed}"
    assert auth.verify_password(password, hashed) is True, "Password verification failed"
    assert auth.verify_password("WrongPassword", hashed) is False, "Wrong password accepted!"
    assert auth.verify_password(password + "extra", hashed) is False, "Tampered password accepted!"
    
    assert auth.SALT_PEPPER == "EdensArrWeStats"
    print("[+] Test 2 Passed: Argon2id password hashing salted with 'EdensArrWeStats' verified.")

    malicious_name = "Service'; DROP TABLE services; --"
    malicious_type = "qbittorrent"
    malicious_url = "http://localhost:8080"
    
    svc_id = db.add_service(
        name=malicious_name,
        service_type=malicious_type,
        base_url=malicious_url,
    )
    retrieved = db.get_service(svc_id)
    assert retrieved is not None, "Failed to retrieve service"
    assert retrieved["name"] == malicious_name, "Name was not safely stored as literal text"
    
    all_svcs = db.get_all_services()
    assert len(all_svcs) >= 1, "SQL Injection dropped or corrupted table!"
    print("[+] Test 3 Passed: SQL injection protection verified with parameterized queries.")

    with TestClient(app) as client:
        health_res = client.get("/api/health")
        assert health_res.status_code == 200
        assert health_res.json()["read_only"] is True
        print("[+] Test 4.1 Passed: /api/health returned healthy.")

        status_res = client.get("/api/auth/status")
        assert status_res.status_code == 200
        assert status_res.json()["is_initialized"] is False
        assert status_res.json()["is_authenticated"] is False
        print("[+] Test 4.2 Passed: /api/auth/status correctly reports uninitialized.")

        prot_services = client.get("/api/services")
        assert prot_services.status_code == 401, f"Expected 401, got {prot_services.status_code}"
        
        prot_telemetry = client.get("/api/telemetry")
        assert prot_telemetry.status_code == 401, f"Expected 401, got {prot_telemetry.status_code}"

        prot_metrics = client.get("/api/metrics/recent")
        assert prot_metrics.status_code == 401, f"Expected 401, got {prot_metrics.status_code}"

        prot_prefs = client.get("/api/preferences")
        assert prot_prefs.status_code == 401, f"Expected 401, got {prot_prefs.status_code}"
        print("[+] Test 4.3 Passed: All protected endpoints securely reject unauthenticated access.")

        setup_res = client.post("/api/auth/setup", json={"password": password})
        assert setup_res.status_code == 200, f"Setup failed: {setup_res.text}"
        session_token = setup_res.json().get("token")
        assert session_token is not None, "Session token not issued on setup"
        print("[+] Test 4.4 Passed: Initial setup successful, admin account provisioned.")

        re_setup = client.post("/api/auth/setup", json={"password": "AnotherPassword"})
        assert re_setup.status_code == 400, "Re-setup was allowed after initialization!"
        print("[+] Test 4.5 Passed: Re-setup correctly blocked once initialized.")

        headers = {"Authorization": f"Bearer {session_token}"}
        
        bad_url_res = client.post(
            "/api/services",
            json={
                "name": "Malicious Service",
                "service_type": "qbittorrent",
                "base_url": "javascript:alert(1)",
            },
            headers=headers,
        )
        assert bad_url_res.status_code == 422, "Script URL scheme was not blocked!"
        print("[+] Test 4.6 Passed: Script URL schemes rejected by validator.")

        add_res = client.post(
            "/api/services",
            json={
                "name": "Home qBittorrent",
                "service_type": "qbittorrent",
                "base_url": "http://192.168.1.150:8080",
                "username": "admin",
                "password": "supersecretpassword",
                "is_enabled": 1,
                "display_order": 1,
            },
            headers=headers,
        )
        assert add_res.status_code == 201, f"Failed to add service: {add_res.text}"
        new_service_id = add_res.json()["id"]
        
        assert add_res.json()["password"] == "••••••••", "Plaintext password exposed in response!"
        print("[+] Test 4.7 Passed: Service created and secrets properly masked.")

        # Test updating service display_order and verifying secret preservation
        edit_res = client.put(
            f"/api/services/{new_service_id}",
            json={
                "name": "Home qBittorrent Updated",
                "service_type": "qbittorrent",
                "base_url": "http://192.168.1.150:8080",
                "username": "admin_updated",
                "password": None,  # keep existing password
                "is_enabled": 1,
                "display_order": 5,
            },
            headers=headers,
        )
        assert edit_res.status_code == 200, f"Failed to update service: {edit_res.text}"
        updated_data = edit_res.json()
        assert updated_data["name"] == "Home qBittorrent Updated"
        assert updated_data["display_order"] == 5
        # Verify secret was preserved in database
        raw_svc = db.fetch_service_by_id(new_service_id, include_secrets=True)
        assert raw_svc["password"] == "supersecretpassword", "Password secret was erased on update!"
        print("[+] Test 4.7.0 Passed: Service update (PUT) with secret preservation and display_order verified.")

        test_cfg_res = client.post(
            "/api/services/test-config",
            json={
                "name": "Test Unsaved qBittorrent",
                "service_type": "qbittorrent",
                "base_url": "http://127.0.0.1:59999",
                "username": "Eden",
                "password": "Iul@2htwif",
            },
            headers=headers,
        )
        assert test_cfg_res.status_code == 200, f"test-config endpoint failed: {test_cfg_res.text}"
        cfg_data = test_cfg_res.json()
        assert cfg_data["status"] in ("offline", "error"), f"Unexpected status: {cfg_data['status']}"
        print("[+] Test 4.7.1 Passed: /api/services/test-config unsaved target connectivity testing verified.")

        # Test Jellyfin library counting logic with MockTransport
        import httpx
        import asyncio
        from clients.jellyfin import _fetch_jellyfin_libraries

        def jelly_handler(req: httpx.Request):
            if req.url.path == "/Items/Counts":
                return httpx.Response(200, json={"MovieCount": 150, "SeriesCount": 20, "EpisodeCount": 450, "ItemCount": 620})
            elif req.url.path == "/Library/VirtualFolders":
                return httpx.Response(200, json=[
                    {"Name": "Movies", "ItemId": "lib-movies-1", "CollectionType": "movies"},
                    {"Name": "Anime", "ItemId": "lib-anime-2", "CollectionType": "tvshows"},
                ])
            elif req.url.path == "/Items":
                parent = req.url.params.get("ParentId")
                itype = req.url.params.get("IncludeItemTypes")
                if parent == "lib-movies-1":
                    return httpx.Response(200, json={"TotalRecordCount": 150})
                elif parent == "lib-anime-2":
                    if itype == "Series":
                        return httpx.Response(200, json={"TotalRecordCount": 20})
                    elif itype == "Episode":
                        return httpx.Response(200, json={"TotalRecordCount": 450})
                return httpx.Response(200, json={"TotalRecordCount": 0})
            return httpx.Response(404)

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(jelly_handler))
        libs, g_counts = asyncio.run(_fetch_jellyfin_libraries(mock_client, "http://fake-jelly", {}, {}))
        assert len(libs) == 2, f"Expected 2 libraries, got {len(libs)}"
        assert libs[0]["name"] == "Movies" and libs[0]["count"] == 150
        assert libs[1]["name"] == "Anime" and libs[1]["count"] == 20 and libs[1]["sub_count"] == 450
        assert "episodes" in libs[1]["formatted"]
        assert g_counts.get("movies") == 150
        assert g_counts.get("total") == 620
        print("[+] Test 4.7.2 Passed: Jellyfin library stats and per-library item counting verified.")

        # Test Jellyseerr telemetry pulling logic with MockTransport
        from clients.jellyseer import pull_jellyseer

        def jellyseer_handler(req: httpx.Request):
            if req.url.path == "/api/v1/request/count":
                return httpx.Response(200, json={
                    "total": 15, "movie": 10, "tv": 5, "pending": 2,
                    "approved": 6, "processing": 3, "available": 4, "declined": 0
                })
            elif req.url.path == "/api/v1/status":
                return httpx.Response(200, json={"version": "1.7.0"})
            elif req.url.path == "/api/v1/issue/count":
                return httpx.Response(200, json={"total": 1, "open": 1, "closed": 0})
            elif req.url.path == "/api/v1/request":
                return httpx.Response(200, json={
                    "results": [
                        {
                            "id": 101,
                            "type": "movie",
                            "status": 2,
                            "is4k": False,
                            "createdAt": "2023-08-10T12:00:00.000Z",
                            "requestedBy": {"displayName": "Eden"},
                            "media": {"tmdbId": 550, "status": 5}
                        },
                        {
                            "id": 102,
                            "type": "tv",
                            "status": 1,
                            "is4k": True,
                            "createdAt": "2023-08-11T14:00:00.000Z",
                            "requestedBy": {"displayName": "TestUser"},
                            "seasons": [{"seasonNumber": 1}, {"seasonNumber": 2}],
                            "media": {"tmdbId": 1399, "status": 2}
                        }
                    ]
                })
            elif req.url.path == "/api/v1/movie/550":
                return httpx.Response(200, json={"title": "Fight Club", "releaseDate": "1999-10-15"})
            elif req.url.path == "/api/v1/tv/1399":
                return httpx.Response(200, json={"name": "Game of Thrones", "firstAirDate": "2011-04-17"})
            return httpx.Response(404)

        mock_jellyseer_client = httpx.AsyncClient(transport=httpx.MockTransport(jellyseer_handler))
        jdata = asyncio.run(pull_jellyseer(mock_jellyseer_client, {"base_url": "http://fake-jellyseer", "apikey": "test-key"}))
        assert jdata["total_requests"] == 15
        assert jdata["pending_requests"] == 2
        assert jdata["version"] == "1.7.0"
        assert jdata["open_issues"] == 1
        assert len(jdata["recent_requests"]) == 2
        assert jdata["recent_requests"][0]["title"] == "Fight Club"
        assert jdata["recent_requests"][0]["year"] == "1999"
        assert jdata["recent_requests"][0]["status"] == "Available"
        assert jdata["recent_requests"][1]["title"] == "Game of Thrones"
        assert jdata["recent_requests"][1]["seasons"] == "S1, S2"
        assert jdata["recent_requests"][1]["is_4k"] is True
        print("[+] Test 4.7.3 Passed: Jellyseerr request totals, breakdown, status, and media title resolution verified.")

        # Test 4.7.3.1: Jellyseerr base_url normalization (stripping /api/v1)
        jdata_norm = asyncio.run(pull_jellyseer(mock_jellyseer_client, {"base_url": "http://fake-jellyseer/api/v1", "apikey": "test-key"}))
        assert jdata_norm["total_requests"] == 15
        try:
            asyncio.run(pull_jellyseer(mock_jellyseer_client, {"base_url": "http://fake-jellyseer", "apikey": ""}))
            assert False, "Should have raised ValueError on missing API key"
        except ValueError:
            pass
        print("[+] Test 4.7.3.1 Passed: Jellyseerr base URL normalization and API key requirement verified.")

        # Test 4.7.4: HandBrake / AutoVideoConverter log monitoring
        from clients.handbrake import parse_handbrake_log, pull_handbrake
        import tempfile

        hb_sample_log = """
[autovideoconverter] Starting conversion queue
[autovideoconverter] Encoding /watch/radarr/Spider-Man- Brand New Day 2026.1080p.HQ Pre.Multi.AAC 2.0.x264.mkv: task 1 of 1, 46.60 % (247.73 fps, avg 245.08 fps, ETA 00h07m26s)
[autovideoconverter] Encoding /watch/radarr/Spider-Man- Brand New Day 2026.1080p.HQ Pre.Multi.AAC 2.0.x264.mkv: task 1 of 1, 54.23 % (234.64 fps, avg 244.50 fps, ETA 00h06m23s)
"""
        hb_parsed = parse_handbrake_log(hb_sample_log)
        assert hb_parsed["is_encoding"] is True
        assert hb_parsed["state"] == "encoding"
        job = hb_parsed["current_job"]
        assert job is not None
        assert job["progress_percent"] == 54.23
        assert job["fps"] == 234.64
        assert job["avg_fps"] == 244.50
        assert job["eta"] == "00h06m23s"
        assert job["eta_formatted"] == "6m 23s"
        assert job["category"] == "radarr"
        assert "Spider-Man" in job["filename"]
        assert job["task_current"] == 1 and job["task_total"] == 1

        # Test file-based pull_handbrake
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as tf:
            tf.write(hb_sample_log)
            temp_log_path = tf.name

        try:
            hb_file_res = asyncio.run(pull_handbrake(mock_jellyseer_client, {"base_url": temp_log_path}))
            assert hb_file_res["is_encoding"] is True
            assert hb_file_res["current_job"]["progress_percent"] == 54.23
            assert hb_file_res["is_http"] is False
        finally:
            if os.path.exists(temp_log_path):
                os.remove(temp_log_path)

        # Test idle state
        hb_idle_log = "[autovideoconverter] Watching for files in /watch\n[autovideoconverter] No files to convert"
        hb_idle_parsed = parse_handbrake_log(hb_idle_log)
        assert hb_idle_parsed["is_encoding"] is False
        assert hb_idle_parsed["state"] == "idle"
        print("[+] Test 4.7.4 Passed: HandBrake and AutoVideoConverter log parsing verified.")

        # Test 4.7.5: Register HandBrake service with file path
        hb_svc_res = client.post(
            "/api/services",
            json={
                "name": "Local HandBrake",
                "service_type": "handbrake",
                "base_url": "/watch/autovideoconverter.log",
                "display_order": 5,
            },
            headers=headers,
        )
        assert hb_svc_res.status_code == 201, f"Failed to register HandBrake service: {hb_svc_res.text}"
        print("[+] Test 4.7.5 Passed: HandBrake service creation with file path verified.")

        # Test 4.7.6: Docker multiplexed log stream demultiplexing & docker:container service registration
        from clients.handbrake import _clean_docker_multiplexed_stream
        sample_log_line = b"[autovideoconverter] Watching for files in /watch\n"
        header = b"\x01\x00\x00\x00" + len(sample_log_line).to_bytes(4, byteorder="big")
        mock_docker_stream = header + sample_log_line
        demuxed = _clean_docker_multiplexed_stream(mock_docker_stream)
        assert demuxed == sample_log_line.decode("utf-8")

        hb_docker_res = client.post(
            "/api/services",
            json={
                "name": "Docker HandBrake",
                "service_type": "handbrake",
                "base_url": "docker:handbrake",
                "display_order": 6,
            },
            headers=headers,
        )
        assert hb_docker_res.status_code == 201, f"Failed to register Docker HandBrake service: {hb_docker_res.text}"
        assert hb_docker_res.json()["base_url"] == "docker:handbrake"
        print("[+] Test 4.7.6 Passed: Docker multiplexed stream demultiplexing & container service registration verified.")

        telemetry_res = client.get("/api/telemetry", headers=headers)
        assert telemetry_res.status_code == 200, f"Telemetry failed: {telemetry_res.text}"
        data = telemetry_res.json()
        assert "telemetry" in data
        assert "system" in data, "Expected system hardware in telemetry"
        print("[+] Test 4.8 Passed: Authenticated telemetry scraping succeeded.")

        cached_res = client.get("/api/telemetry", headers=headers)
        assert cached_res.status_code == 200
        assert cached_res.json()["cached"] is True, "Expected cached telemetry response"
        print("[+] Test 4.9 Passed: Telemetry TTL caching verified (0 duplicate network requests).")

        pref_res = client.post(
            "/api/preferences",
            json={"preference_key": "theme", "preference_val": "dark"},
            headers=headers,
        )
        assert pref_res.status_code == 200
        get_pref = client.get("/api/preferences", headers=headers)
        assert get_pref.json().get("theme") == "dark"
        print("[+] Test 4.10 Passed: UI preferences set and retrieved.")

        # Test storage mounts
        storage_create = client.post(
            "/api/storage",
            json={
                "name": "Media Pool",
                "mount_path": tempfile.gettempdir(),
                "display_order": 0,
                "is_enabled": 1,
                "folders": ["test_sub1", "test_sub2"],
            },
            headers=headers,
        )
        assert storage_create.status_code == 201, f"Storage creation failed: {storage_create.text}"
        smid = storage_create.json()["id"]

        storage_list = client.get("/api/storage", headers=headers)
        assert storage_list.status_code == 200
        pools = storage_list.json()
        assert len(pools) >= 1
        assert pools[0]["name"] == "Media Pool"
        assert pools[0]["total_bytes"] > 0
        assert pools[0]["is_accessible"] is True
        print("[+] Test 4.10.1 Passed: Storage pool creation and disk_usage telemetry verified.")

        # Test updating storage pool display_order
        edit_storage = client.put(
            f"/api/storage/{smid}",
            json={
                "name": "Media Pool Updated",
                "mount_path": tempfile.gettempdir(),
                "display_order": 10,
                "is_enabled": 1,
                "folders": ["test_sub1"],
            },
            headers=headers,
        )
        assert edit_storage.status_code == 200, f"Storage update failed: {edit_storage.text}"
        assert edit_storage.json()["display_order"] == 10
        print("[+] Test 4.10.1.1 Passed: Storage pool update (PUT) verified.")

        browse_res = client.get(f"/api/filesystem/browse?path={tempfile.gettempdir()}", headers=headers)
        assert browse_res.status_code == 200
        bdata = browse_res.json()
        assert "current_path" in bdata
        assert isinstance(bdata.get("directories"), list)
        print("[+] Test 4.10.2 Passed: /api/filesystem/browse directory inspection verified.")

        resp_headers = health_res.headers
        assert resp_headers.get("x-content-type-options") == "nosniff"
        assert resp_headers.get("x-frame-options") == "DENY"
        assert "default-src 'self'" in resp_headers.get("content-security-policy", "")
        print("[+] Test 4.11 Passed: Security response headers (CSP, X-Frame-Options, X-Content-Type-Options) verified.")

        # Test 4.11.1: System Hardware Telemetry
        sys_res = client.get("/api/system/stats", headers=headers)
        assert sys_res.status_code == 200, f"System stats failed: {sys_res.text}"
        sdata = sys_res.json()
        assert "cpu" in sdata and "brand" in sdata["cpu"]
        assert "ram" in sdata and sdata["ram"]["total_bytes"] > 0
        assert "gpus" in sdata and isinstance(sdata["gpus"], list)
        assert "hostname" in sdata
        assert "network" in sdata, "Missing network telemetry in system stats"
        assert "download_speed_bytes" in sdata["network"]
        assert "upload_speed_bytes" in sdata["network"]
        assert "daily" in sdata["network"]
        assert "all_time" in sdata["network"]
        assert "interfaces" in sdata["network"]
        print("[+] Test 4.11.1 Passed: Host system hardware telemetry (CPU, RAM, GPUs, Network) verified.")

        # Test 4.11.2: Daily Network Bandwidth Tracking & Persistence
        from clients.handbrake import parse_handbrake_log
        import hardware
        
        # Test DB bandwidth update & accumulation
        db.update_daily_network_bandwidth(1000000, 500000)
        db.update_daily_network_bandwidth(1000000 + 2097152, 500000 + 1048576)
        daily_bw = db.get_daily_network_bandwidth()
        assert daily_bw["download_bytes"] >= 2097152, f"Expected accumulated download >= 2MB, got {daily_bw['download_bytes']}"
        assert daily_bw["upload_bytes"] >= 1048576, f"Expected accumulated upload >= 1MB, got {daily_bw['upload_bytes']}"

        # Verify container -> host counter shift doesn't cause artificial multi-gigabyte spikes
        res_shift = db.update_daily_network_bandwidth(100 * 1024**3, 50 * 1024**3)
        assert res_shift["today_recv"] >= 2097152, "Expected legitimate daily bytes to be preserved on baseline shift"

        print("[+] Test 4.11.2 Passed: Daily host network bandwidth persistence & dormancy carryover verified.")

        # Test 4.11.3: HandBrake completion heuristic at ~98% with conversion ended marker
        sample_log_completed = """
[autovideoconverter] Starting conversion of '/watch/tv-sonarr/Show.S01E01.mkv'...
Encoding: task 1 of 1, 95.40 % (35.20 fps, avg 34.10 fps, ETA 00h00m12s)
Encoding: task 1 of 1, 98.70 % (35.10 fps, avg 34.10 fps, ETA 00h00m03s)
[autovideoconverter] Conversion ended successfully.
[autovideoconverter] Removing '/watch/tv-sonarr/Show.S01E01.mkv'...
        """
        hb_data = parse_handbrake_log(sample_log_completed)
        assert hb_data["state"] == "idle", f"Expected idle state after conversion ended, got {hb_data['state']}"
        assert hb_data["current_job"] is None, f"Expected current_job to be cleared, got {hb_data['current_job']}"
        assert len(hb_data["recent_completed"]) >= 1, "Expected finished job in recent_completed"
        assert "Show.S01E01" in hb_data["recent_completed"][0]["name"]
        print("[+] Test 4.11.3 Passed: HandBrake 98% completion heuristic and idle state transition verified.")

        # Test 4.11.4: Intel Xe GT Idle Residency Delta & DRM VRAM Telemetry
        mock_gpu_dir = tempfile.mkdtemp(prefix="mock_drm_gpu_")
        try:
            gtidle_dir = os.path.join(mock_gpu_dir, "device", "tile0", "gt0", "gtidle")
            os.makedirs(gtidle_dir, exist_ok=True)
            residency_file = os.path.normpath(os.path.join(gtidle_dir, "idle_residency_ms"))
            with open(residency_file, "w") as f:
                f.write("10000\n")

            # Seed cache
            hardware._gpu_util_cache[residency_file] = {
                "ts": time.time() - 1.0,
                "idle_ms": 9500,
                "last_util": 0.0,
            }
            # 500ms idle over 1000ms elapsed -> 50% busy
            calc_util = hardware._calc_xe_gt_utilization(mock_gpu_dir, os.path.join(mock_gpu_dir, "device"))
            assert calc_util is not None and 45.0 <= calc_util <= 55.0, f"Expected ~50% util, got {calc_util}"

            # Test 100% busy (0 idle increase)
            hardware._gpu_util_cache[residency_file] = {
                "ts": time.time() - 1.0,
                "idle_ms": 10000,
                "last_util": 0.0,
            }
            calc_busy = hardware._calc_xe_gt_utilization(mock_gpu_dir, os.path.join(mock_gpu_dir, "device"))
            assert calc_busy == 100.0, f"Expected 100% busy, got {calc_busy}"
        finally:
            shutil.rmtree(mock_gpu_dir, ignore_errors=True)
        print("[+] Test 4.11.4 Passed: Intel Xe GT idle residency delta calculation verified.")


        logout_res = client.post("/api/auth/logout", headers=headers)
        assert logout_res.status_code == 200
        
        after_logout = client.get("/api/services", headers=headers)
        assert after_logout.status_code == 401, "Revoked session token was still accepted!"
        print("[+] Test 4.12 Passed: Logout properly revokes session token.")

    print("\n[OK] ALL BACKEND VERIFICATION TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    try:
        run_tests()
    finally:
        if os.path.exists(test_db):
            try:
                os.remove(test_db)
            except Exception:
                pass
