# IPTV Auditor (Unraid Edition)

A high-performance web application designed for Unraid and Docker to decode, decrypt, batch audit, and test IPTV services (Xtream Codes API & M3U playlists).

---

## ✨ Features

- **Extreme Speed & High Parallelism**:
  - **Turbo Mode**: Audits servers in ~100–200ms by querying categories and live streams concurrently, avoiding multi-megabyte VOD catalog downloads.
  - **Configurable Workers**: Supports 10, 25, 40, or 50 simultaneous parallel checks.
  - **Dead-Host Caching**: Instantly detects and remembers dead domains and failed DNS lookups, skipping redundant timeouts.
  - **Live Speedometer**: Displays real-time checking rate (e.g. *~25 servers/sec*).
- **Interactive Controls (Start / Pause / Stop)**:
  - **Pause & Resume**: Pause the live queue anytime without losing state; resume with one click.
  - **Stop**: Gracefully terminates the running audit and retains all collected results in the table.
- **WireGuard (`wg0`) VPN Integration**:
  - Preconfigured to route all container audit traffic through your Unraid `wg0` VPN network interface.
- **Multi-Format Input & Decryption**:
  - Automatically decodes **Base64** and Unix **uuencoded** strings.
  - Natively decrypts **`paste.sh` client-side encrypted pastes** (`https://paste.sh/<id>#<key>`) via AES-256-CBC.
  - Supports direct URLs, raw M3U playlist links, and key-value credential blocks (`Host: ... User: ... Pass: ...`).
- **Comprehensive Server Auditing**:
  - **Account Status**: Active, Expired, Disabled, or Unreachable.
  - **Connection Limits**: Active connections vs Max allowed connections (`active_cons / max_connections`).
  - **Expiration Details**: Human-readable expiration date with relative countdown (e.g. *Expires in ~9 months*).
  - **Content Counts**: Live TV channels, Movies (VOD), and TV Series.
  - **Adult Content Detection**: Automatically scans categories and stream names for adult keywords (`18+`, `XXX`, `Adult`, `For Adults`, etc.) and displays a status badge.
  - **Live Stream Probing**: Performs a lightweight HTTP stream probe to verify video playback and detect panel / ISP blocks.
- **Modern Responsive Web UI**:
  - Dark mode styled with Unraid aesthetics (Tailwind CSS).
  - Search & filter by status, adult content, or playable streams.
  - One-click copy for individual M3U links, Xtream credentials, or all active playlists.
  - One-click CSV export and a built-in **"Load Samples"** button.

---

## 🚀 Setup on Unraid (Docker Compose Manager)

1. Open your **Unraid WebGUI** &rarr; **Docker** tab.
2. In the **Docker Compose Manager** section, click **Add New Stack** and name it `iptv-audit`.
3. Click the gear icon on the stack and select **Edit Compose File**.
4. Paste the following compose configuration:

```yaml
services:
  iptv-audit:
    build:
      context: https://github.com/tsneidin/iptv_audit_ag.git#main
    container_name: iptv-audit
    restart: unless-stopped
    ports:
      - "8180:8180"
    networks:
      - wg0
    environment:
      - PORT=8180
      - MAX_CONCURRENT_CHECKS=25
      - REQUEST_TIMEOUT=4.0
      - PROBE_STREAMS=true
      - PROBE_TIMEOUT=2.5
      - USER_AGENT=IPTVSmartersPlayer

networks:
  wg0:
    external: true
```

5. Click **Compose Up**.
6. Access the dashboard at:
   ```
   http://192.168.86.86:8180
   ```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8180` | Web server port |
| `MAX_CONCURRENT_CHECKS` | `25` | Number of simultaneous server audits (up to 50) |
| `REQUEST_TIMEOUT` | `4.0` | API request timeout in seconds |
| `PROBE_STREAMS` | `true` | Whether to probe live video streams |
| `PROBE_TIMEOUT` | `2.5` | Timeout in seconds for stream chunk probe |
| `AUDIT_MODE` | `turbo` | Audit mode: `turbo` (fast) or `deep` |
| `USER_AGENT` | `IPTVSmartersPlayer` | Custom User-Agent header for IPTV requests |

---

## 📄 License
MIT License
