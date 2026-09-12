import os
import sys
import tempfile
import importlib

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

        telemetry_res = client.get("/api/telemetry", headers=headers)
        assert telemetry_res.status_code == 200, f"Telemetry failed: {telemetry_res.text}"
        data = telemetry_res.json()
        assert "telemetry" in data
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

        resp_headers = health_res.headers
        assert resp_headers.get("x-content-type-options") == "nosniff"
        assert resp_headers.get("x-frame-options") == "DENY"
        assert "default-src 'self'" in resp_headers.get("content-security-policy", "")
        print("[+] Test 4.11 Passed: Security response headers (CSP, X-Frame-Options, X-Content-Type-Options) verified.")

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
