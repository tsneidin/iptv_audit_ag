# IPTV Auditor (Unraid Edition)

A high-performance web application designed for Unraid and Docker to decode, decrypt, batch audit, and test IPTV services (Xtream Codes API & M3U playlists).

---

## ✨ Features

- **Multi-Format Input & Decryption**:
  - Automatically decodes **Base64** and Unix **uuencoded** strings.
  - Natively decrypts **`paste.sh` client-side encrypted pastes** (`https://paste.sh/<id>#<key>`) via AES-256-CBC.
  - Supports direct URLs, raw M3U playlist links, and key-value credential blocks (`Host: ... User: ... Pass: ...`).
- **Comprehensive Server Auditing**:
  - **Account Status**: Active, Expired, Disabled, or Unreachable.
  - **Connection Limits**: Live / Active connections vs Max allowed connections (`active_cons / max_connections`).
  - **Expiration Details**: Human-readable expiration date with relative countdown (e.g. *Expires in ~9 months*).
  - **Content Counts**: Live TV channels, Movies (VOD), and TV Series.
  - **Adult Content Detection**: Automatically scans categories and stream names for adult keywords (`18+`, `XXX`, `Adult`, `For Adults`, etc.) and displays a status badge.
  - **Live Stream Probing**: Performs a lightweight HTTP stream probe to verify video playback and detect panel / ISP blocks.
- **Asynchronous & Real-Time**:
  - Built on **FastAPI** with an async worker pool.
  - Real-time progress updates streamed to the browser using **Server-Sent Events (SSE)**.
- **Modern Responsive Web UI**:
  - Dark mode styled with Unraid aesthetics (Tailwind CSS).
  - Search & filter by status, adult content, or playable streams.
  - One-click copy for individual M3U links, Xtream credentials, or all active playlists.
  - One-click CSV export.
  - Built-in "Load Samples" button to quickly test with pre-configured samples.

---

## 🚀 Quick Setup on Unraid (Docker Compose Manager)

1. Open your **Unraid WebGUI**.
2. Navigate to the **Docker** tab.
3. Scroll to the **Docker Compose** section (or open the **Compose Manager** plugin).
4. Click **Add New Stack** and name it `iptv-audit`.
5. Click the gear icon on the new stack and select **Edit Compose File**.
6. Paste the contents of [`docker-compose.yml`](docker-compose.yml):

```yaml
services:
  iptv-audit:
    build:
      context: https://github.com/tsneidin/iptv_audit_ag.git#main
    container_name: iptv-audit
    restart: unless-stopped
    ports:
      - "8180:8180"
    environment:
      - PORT=8180
      - MAX_CONCURRENT_CHECKS=8
      - REQUEST_TIMEOUT=6.0
      - PROBE_STREAMS=true
      - PROBE_TIMEOUT=4.0
      - USER_AGENT=IPTVSmartersPlayer
```

> **Note on Updates**: Because this stack builds from source rather than pulling from Docker Hub, do not click the "Update" (Pull) button in Compose Manager. Instead, click **Compose Down** and then **Compose Up** to build and start the latest version.
>
> Alternatively, you can use the pre-built GitHub Container Registry image if you prefer one-click updates:
> ```yaml
> image: ghcr.io/tsneidin/iptv_audit_ag:latest
> ```

*(Alternatively, if you cloned this repo directly onto your Unraid server into `/boot/config/plugins/dockerMan/templates-user/projects/iptv-audit` or `/mnt/user/appdata/iptv-audit`, simply run `docker compose up -d`)*.

7. Click **Compose Up**.
8. Access the web dashboard at:
   ```
   http://<YOUR_UNRAID_IP>:8180
   ```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8180` | Web server port |
| `MAX_CONCURRENT_CHECKS` | `8` | Number of simultaneous server audits |
| `REQUEST_TIMEOUT` | `6.0` | API request timeout in seconds |
| `PROBE_STREAMS` | `true` | Whether to probe live video streams |
| `PROBE_TIMEOUT` | `4.0` | Timeout in seconds for stream chunk probe |
| `USER_AGENT` | `IPTVSmartersPlayer` | Custom User-Agent header for IPTV requests |

---

## 💻 Local / Development Run

```bash
# Clone the repository
git clone https://github.com/tsneidin/iptv_audit_ag.git
cd iptv_audit_ag

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
python -m unittest discover tests

# Start application
PORT=8180 uvicorn app.main:app --host 0.0.0.0 --port 8180 --reload
```

---

## 📄 License
MIT License
