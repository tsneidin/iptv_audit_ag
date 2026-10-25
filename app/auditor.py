import asyncio
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel

from app.config import config
from app.parser import IPTVServer

logger = logging.getLogger(__name__)

ADULT_KEYWORDS = [
    "xxx",
    "adult",
    "+18",
    "18+",
    "for adult",
    "erotic",
    "porn",
    "playboy",
    "hustler",
    "redlight",
    "red light",
    "brazzers",
    "dorcel",
    "penthouse",
    "vivid",
    "sensual",
    "babes",
]


class AuditResult(BaseModel):
    host: str
    username: str
    password: str
    is_working: bool
    status: str
    status_badge: str  # active, expired, invalid, offline, busy
    max_connections: int = 0
    active_connections: int = 0
    exp_date: Optional[str] = None
    exp_countdown: Optional[str] = None
    live_channels: int = 0
    movies_vod: int = 0
    series: int = 0
    has_adult: bool = False
    adult_details: str = "None"
    stream_probe: str = "Skipped"
    stream_probe_badge: str = "gray"  # green, yellow, red, gray
    latency_ms: int = 0
    m3u_url: str
    error_message: Optional[str] = None


def format_expiration(exp_val: Any) -> tuple[Optional[str], Optional[str]]:
    """Converts timestamp or date string into readable date and relative countdown."""
    if not exp_val:
        return "Unlimited", "Lifetime / No Expiration"

    try:
        if isinstance(exp_val, (int, float)) or (isinstance(exp_val, str) and exp_val.isdigit()):
            ts = int(exp_val)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            # Try ISO or standard datetime strings
            dt = datetime.fromisoformat(str(exp_val).replace("Z", "+00:00"))

        date_str = dt.strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc)
        diff = dt - now

        days = diff.days
        if days < 0:
            countdown = f"Expired {abs(days)} days ago"
        elif days == 0:
            countdown = "Expires today!"
        elif days < 30:
            countdown = f"Expires in {days} days"
        elif days < 365:
            months = round(days / 30)
            countdown = f"Expires in ~{months} month{'s' if months > 1 else ''}"
        else:
            years = round(days / 365, 1)
            countdown = f"Expires in ~{years} years"

        return date_str, countdown
    except Exception:
        return str(exp_val), ""


def check_adult(name: str) -> bool:
    nl = name.lower()
    return any(w in nl for w in ADULT_KEYWORDS)


async def test_live_stream_probe(
    client: httpx.AsyncClient,
    server: IPTVServer,
    stream_id: Any,
    active_cons: int,
    max_cons: int,
) -> tuple[str, str]:
    """
    Attempts to read the first few kilobytes of a live channel stream
    to verify playback.
    """
    if not stream_id:
        return "No Stream ID", "gray"

    stream_url = f"{server.host}/live/{server.username}/{server.password}/{stream_id}.ts"
    try:
        async with client.stream(
            "GET",
            stream_url,
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.PROBE_TIMEOUT,
        ) as resp:
            if resp.status_code == 200:
                bytes_read = 0
                async for chunk in resp.aiter_bytes():
                    bytes_read += len(chunk)
                    if bytes_read >= 4096:
                        break
                if bytes_read > 0:
                    return f"Playable ({round(bytes_read / 1024, 1)} KB read)", "green"
                return "Playable (empty response)", "yellow"
            elif resp.status_code == 401:
                if active_cons >= max_cons and max_cons > 0:
                    return f"Max Conns Busy ({active_cons}/{max_cons})", "yellow"
                return "Stream Unauthorized (401)", "red"
            elif resp.status_code == 511:
                return "ISP / Panel Blocked (511)", "red"
            else:
                return f"HTTP {resp.status_code}", "red"
    except httpx.TimeoutException:
        return "Stream Timeout", "yellow"
    except Exception as e:
        err = str(e)
        if "401" in err:
            return "Stream 401 Unauthorized", "red"
        return f"Probe Error ({type(e).__name__})", "red"


async def audit_iptv_server(
    server: IPTVServer,
    client: httpx.AsyncClient,
    probe_stream: bool = True,
) -> AuditResult:
    """
    Tests an individual IPTV server credentials against Xtream Codes API
    and live stream endpoint.
    """
    start_time = time.time()
    api_url = f"{server.host}/player_api.php?username={server.username}&password={server.password}"

    try:
        resp = await client.get(
            api_url,
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.REQUEST_TIMEOUT,
        )
        latency = int((time.time() - start_time) * 1000)

        if resp.status_code != 200:
            return AuditResult(
                host=server.host,
                username=server.username,
                password=server.password,
                is_working=False,
                status=f"HTTP {resp.status_code}",
                status_badge="invalid",
                latency_ms=latency,
                m3u_url=server.standard_m3u_url,
                error_message=f"Server returned HTTP {resp.status_code}",
            )

        try:
            data = resp.json()
        except Exception:
            return AuditResult(
                host=server.host,
                username=server.username,
                password=server.password,
                is_working=False,
                status="Invalid JSON",
                status_badge="invalid",
                latency_ms=latency,
                m3u_url=server.standard_m3u_url,
                error_message="Response was not valid Xtream JSON",
            )

        user_info = data.get("user_info", {})
        if not user_info:
            return AuditResult(
                host=server.host,
                username=server.username,
                password=server.password,
                is_working=False,
                status="No User Info",
                status_badge="invalid",
                latency_ms=latency,
                m3u_url=server.standard_m3u_url,
                error_message="Missing user_info in response",
            )

        # Auth check
        auth = user_info.get("auth")
        raw_status = str(user_info.get("status", "")).strip().capitalize()
        if auth == 0 or raw_status.lower() in ("disabled", "banned", "deleted"):
            return AuditResult(
                host=server.host,
                username=server.username,
                password=server.password,
                is_working=False,
                status=raw_status or "Disabled / Auth Failed",
                status_badge="invalid",
                latency_ms=latency,
                m3u_url=server.standard_m3u_url,
                error_message=user_info.get("message") or "Authentication failed",
            )

        # Expiration
        exp_date_raw = user_info.get("exp_date")
        exp_str, exp_countdown = format_expiration(exp_date_raw)

        is_expired = False
        if exp_countdown and "Expired" in exp_countdown:
            is_expired = True

        max_cons = int(user_info.get("max_connections") or 1)
        active_cons = int(user_info.get("active_cons") or 0)

        # Query categories & streams for accurate counts & adult detection
        live_count = 0
        vod_count = 0
        series_count = 0
        adult_detected = False
        adult_matches: List[str] = []
        candidate_stream_id = None

        # Helper to fetch endpoint
        async def fetch_endpoint(action: str):
            try:
                r = await client.get(
                    f"{api_url}&action={action}",
                    headers={"User-Agent": config.USER_AGENT},
                    timeout=config.REQUEST_TIMEOUT,
                )
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
            return None

        # Fetch in parallel
        live_res, vod_res, series_res, live_cats_res = await asyncio.gather(
            fetch_endpoint("get_live_streams"),
            fetch_endpoint("get_vod_streams"),
            fetch_endpoint("get_series"),
            fetch_endpoint("get_live_categories"),
        )

        # Process Live Streams
        if isinstance(live_res, list):
            live_count = len(live_res)
            for item in live_res:
                name = item.get("name", "")
                if not candidate_stream_id and item.get("stream_id") and not name.startswith(("-=", "###", "===")):
                    candidate_stream_id = item.get("stream_id")
                if check_adult(name):
                    adult_detected = True
                    if len(adult_matches) < 3:
                        adult_matches.append(name)
        elif isinstance(live_cats_res, list):
            live_count = len(live_cats_res)  # fallback estimate

        # Process VOD Movies
        if isinstance(vod_res, list):
            vod_count = len(vod_res)
            for item in vod_res:
                name = item.get("name", "")
                if check_adult(name):
                    adult_detected = True
                    if len(adult_matches) < 3:
                        adult_matches.append(name)

        # Process Series
        if isinstance(series_res, list):
            series_count = len(series_res)

        # Check Live Categories for adult tags
        if isinstance(live_cats_res, list):
            for cat in live_cats_res:
                cat_name = cat.get("category_name", "")
                if check_adult(cat_name):
                    adult_detected = True
                    if len(adult_matches) < 3:
                        adult_matches.append(cat_name)

        adult_details = "None"
        if adult_detected:
            adult_details = f"Yes ({', '.join(adult_matches[:2])})" if adult_matches else "Yes"

        # Stream Probing (if enabled and server has live channels)
        stream_probe_status = "Skipped"
        stream_badge = "gray"
        if probe_stream and candidate_stream_id:
            stream_probe_status, stream_badge = await test_live_stream_probe(
                client=client,
                server=server,
                stream_id=candidate_stream_id,
                active_cons=active_cons,
                max_cons=max_cons,
            )

        status_text = "Expired" if is_expired else (raw_status or "Active")
        status_badge = "expired" if is_expired else "active"

        return AuditResult(
            host=server.host,
            username=server.username,
            password=server.password,
            is_working=not is_expired,
            status=status_text,
            status_badge=status_badge,
            max_connections=max_cons,
            active_connections=active_cons,
            exp_date=exp_str,
            exp_countdown=exp_countdown,
            live_channels=live_count,
            movies_vod=vod_count,
            series=series_count,
            has_adult=adult_detected,
            adult_details=adult_details,
            stream_probe=stream_probe_status,
            stream_probe_badge=stream_badge,
            latency_ms=latency,
            m3u_url=server.standard_m3u_url,
        )

    except httpx.ConnectError:
        return AuditResult(
            host=server.host,
            username=server.username,
            password=server.password,
            is_working=False,
            status="Offline / Unreachable",
            status_badge="offline",
            m3u_url=server.standard_m3u_url,
            error_message="Host connection failed or domain does not exist",
        )
    except httpx.TimeoutException:
        return AuditResult(
            host=server.host,
            username=server.username,
            password=server.password,
            is_working=False,
            status="Connection Timeout",
            status_badge="offline",
            m3u_url=server.standard_m3u_url,
            error_message="Connection timed out",
        )
    except Exception as e:
        logger.exception("Audit error for %s", server.host)
        return AuditResult(
            host=server.host,
            username=server.username,
            password=server.password,
            is_working=False,
            status="Error",
            status_badge="offline",
            m3u_url=server.standard_m3u_url,
            error_message=str(e),
        )
