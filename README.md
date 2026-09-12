# ArrWeStatistics

Lightweight, single-binary read-only telemetry dashboard for self-hosted media and download stacks. Aggregates live status, speeds, and queues from qBittorrent, SABnzbd, Jellyfin, and Jellyseerr.

[![Build and Publish Docker Image](https://github.com/EdenFails/ArrWeStatistics/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/EdenFails/ArrWeStatistics/actions/workflows/docker-publish.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue?style=flat-square)
![Docker](https://img.shields.io/badge/docker-ghcr.io-blue?style=flat-square)
![Port](https://img.shields.io/badge/port-8478-green?style=flat-square)

---

## Design Invariants

- **Strict Read-Only**: Completely lacks mutation or destructive methods. No endpoints or UI controls exist for pausing, deleting, resuming, or restarting services or downloads.
- **Zero ORM Overhead**: Direct `sqlite3` integration using Write-Ahead Logging (WAL mode), enforced foreign keys, and parameterized queries.
- **Demand-Driven Polling**: Scrapes clients concurrently via `httpx.AsyncClient` only when an active browser tab is viewing the dashboard. Polling pauses on tab visibility loss.
- **In-Memory Cache**: Telemetry queries within the TTL window (default 10s) serve from RAM with 0ms network latency.
- **Hardened Security**: Argon2id password hashing with application-level salting, HttpOnly session cookies, brute-force rate limits, and Content Security Policy headers.

---

## Supported Services

| Service | Protocol | Scraped Metrics |
| :--- | :--- | :--- |
| **qBittorrent** | WebUI API v2 | Download/upload rates, torrent counts, disk free space, active transfer list |
| **SABnzbd** | JSON Web API | Queue speed, size remaining, time left, active slot progress |
| **Jellyfin** | REST API | Active playback streams, transcode vs direct play, hardware acceleration |
| **Jellyseerr** | REST API | Request counters (pending, approved, available), recent requests log |

---

## Quick Start (Docker Compose)

The pre-built image is published to GitHub Container Registry (`ghcr.io`).

```yaml
version: '3.8'

services:
  arrwestatistics:
    image: ghcr.io/edenfails/arrwestatistics:latest
    container_name: arrwestatistics
    restart: unless-stopped
    ports:
      - "8478:8478"
    environment:
      - HOST=0.0.0.0
      - PORT=8478
      - DB_PATH=/app/data/arrwestatistics.db
      - CACHE_TTL_SECONDS=10
    volumes:
      - ./data:/app/data
    deploy:
      resources:
        limits:
          cpus: '0.50'
          memory: 256M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8478/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

Run container:
```bash
docker compose up -d
```
Access dashboard at `http://<server-ip>:8478`.

> [!NOTE]
> On first load, the setup screen prompts for an administrator master password. Once set, the onboarding endpoint permanently locks.

---

## Nginx Proxy Manager Setup

To route ArrWeStatistics through Nginx Proxy Manager (NPM):

<details>
<summary><b>Option 1: Host / Bridge Network (Standard)</b></summary>

If your Docker host runs NPM or you use port forwarding:

1. In NPM, click **Add Proxy Host**.
2. **Details Tab**:
   - **Domain Names**: `stats.yourdomain.com`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: LAN IP of your Docker server (e.g. `192.168.1.50`)
   - **Forward Port**: `8478`
   - Check **Block Common Exploits**
   - Check **Websockets Support**
3. **SSL Tab**:
   - Select or request a Let's Encrypt certificate.
   - Check **Force SSL** and **HTTP/2 Support**.
4. Click **Save**.

</details>

<details>
<summary><b>Option 2: Docker Network Integration (Internal)</b></summary>

If NPM runs in Docker and shares a custom network (e.g. `npm-net`):

1. Add the shared network to `docker-compose.yml`:
   ```yaml
   networks:
     default:
       external:
         name: npm-net
   ```
2. In NPM Proxy Host:
   - **Forward Hostname / IP**: `arrwestatistics`
   - **Forward Port**: `8478`
   - **Scheme**: `http`
   - Check **Websockets Support** and configure SSL.

</details>

---

## Updating the Container

Pull the latest published image and restart:

```bash
docker compose pull
docker compose up -d
```

---

## Local Development

```bash
# Clone repository
git clone https://github.com/EdenFails/ArrWeStatistics.git
cd ArrWeStatistics

# Install requirements
pip install -r requirements.txt

# Run server
python Main.py
```

Run test suite:
```bash
python test_backend.py
```

---

## Project Structure

```
ArrWeStatistics/
├── .github/workflows/
│   └── docker-publish.yml      # Automated GHCR multi-arch build
├── clients/
│   ├── __init__.py             # Client registry & async gather pool
│   ├── jellyfin.py             # Active playback & transcode monitor
│   ├── jellyseer.py            # Media request queue scraper
│   ├── qbittorrent.py          # Session-cached torrent monitor
│   └── sabnzbd.py              # Usenet queue & bandwidth scraper
├── WebInterface/
│   ├── index.html              # Single-page interface
│   ├── css/style.css           # Flat minimalist styling
│   └── js/
│       ├── app.js              # State machine & visibility polling loop
│       └── components.js       # Modular service cards
├── auth.py                     # Salted Argon2id hashing & session manager
├── database.py                 # SQLite WAL connection factory & CRUD
├── Main.py                     # FastAPI application root & static mount
├── test_backend.py             # 12-point automated verification suite
├── Dockerfile                  # Multi-stage Python 3.12 slim build
└── docker-compose.yml          # Container configuration
```

---

<details>
<summary><b>API Route Reference</b></summary>

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | Public | Container health check |
| `GET` | `/api/auth/status` | Public | System setup & auth state |
| `POST` | `/api/auth/setup` | Public | Initial master password configuration |
| `POST` | `/api/auth/login` | Public | Authenticates admin session |
| `POST` | `/api/auth/logout` | Required | Revokes session token |
| `GET` | `/api/services` | Required | List configured targets (secrets masked) |
| `POST` | `/api/services` | Required | Register target service |
| `POST` | `/api/services/{id}/test` | Required | Run test scrape against target |
| `DELETE` | `/api/services/{id}` | Required | Remove target and cascade metrics |
| `GET` | `/api/telemetry` | Required | Aggregate poll with TTL cache |
| `GET` | `/api/metrics/recent` | Required | Historical latency samples |

</details>

---

*Note: Coded with AI.*
