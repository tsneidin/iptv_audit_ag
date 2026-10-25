import asyncio
import csv
import io
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from pydantic import BaseModel

from app.auditor import AuditResult, audit_iptv_server
from app.config import config
from app.decoder import extract_urls_from_input, fetch_url_content
from app.parser import IPTVServer, extract_iptv_servers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("iptv_audit")

app = FastAPI(title="IPTV Audit", version="1.1.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


class AuditSession:
    """Manages pause, resume, and stop state for an audit run."""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._paused = asyncio.Event()
        self._paused.set()  # set means NOT paused (running)
        self.is_stopped = False

    def pause(self):
        self._paused.clear()

    def resume(self):
        self._paused.set()

    def stop(self):
        self.is_stopped = True
        self._paused.set()  # unblock if paused so loop can terminate

    async def wait_if_paused(self):
        await self._paused.wait()

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()


# Store active sessions in memory
active_sessions: Dict[str, AuditSession] = {}


class AuditRequest(BaseModel):
    input_text: str
    probe_stream: bool = True
    concurrency: int = 25
    audit_mode: str = "turbo"  # "turbo" or "deep"
    session_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_port": config.PORT,
            "probe_streams_default": config.PROBE_STREAMS,
            "default_concurrency": config.MAX_CONCURRENT_CHECKS,
        },
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "iptv-audit", "version": "1.1.0"}


@app.post("/api/audit/pause/{session_id}")
async def pause_audit(session_id: str):
    session = active_sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    session.pause()
    return {"status": "paused", "session_id": session_id}


@app.post("/api/audit/resume/{session_id}")
async def resume_audit(session_id: str):
    session = active_sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    session.resume()
    return {"status": "resumed", "session_id": session_id}


@app.post("/api/audit/stop/{session_id}")
async def stop_audit(session_id: str):
    session = active_sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    session.stop()
    return {"status": "stopped", "session_id": session_id}


async def run_audit_stream(payload: AuditRequest, session: AuditSession) -> AsyncGenerator[str, None]:
    """
    High-throughput async generator with session pause/stop controls,
    dead-host caching, and configurable concurrency up to 50 workers.
    """
    yield f"data: {json.dumps({'type': 'session_init', 'session_id': session.session_id})}\n\n"
    yield f"data: {json.dumps({'type': 'status', 'message': 'Extracting and decoding URLs...'})}\n\n"

    urls = extract_urls_from_input(payload.input_text)
    if not urls:
        direct_servers = extract_iptv_servers(payload.input_text)
        if not direct_servers:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No valid URLs, encoded strings, or IPTV credentials found in input.'})}\n\n"
            return
        all_servers = direct_servers
    else:
        yield f"data: {json.dumps({'type': 'extracted_urls', 'urls': urls, 'message': f'Found {len(urls)} sources to fetch and decode.'})}\n\n"

        # High-performance fetch pool
        limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
        async with httpx.AsyncClient(verify=False, limits=limits, timeout=config.REQUEST_TIMEOUT) as client:
            all_servers: List[IPTVServer] = []
            seen_keys = set()

            for idx, url in enumerate(urls, 1):
                if session.is_stopped:
                    yield f"data: {json.dumps({'type': 'audit_stopped', 'message': 'Audit stopped by user.'})}\n\n"
                    return
                await session.wait_if_paused()

                yield f"data: {json.dumps({'type': 'status', 'message': f'Fetching source {idx}/{len(urls)}: {url[:60]}...'})}\n\n"
                try:
                    _, content = await fetch_url_content(url, client)
                    servers = extract_iptv_servers(content, source_url=url)
                    for s in servers:
                        if s.key not in seen_keys:
                            seen_keys.add(s.key)
                            all_servers.append(s)
                except Exception as e:
                    logger.warning("Failed to fetch or decrypt %s: %s", url, e)
                    yield f"data: {json.dumps({'type': 'warning', 'message': f'Failed to process source: {str(e)}'})}\n\n"

    if not all_servers:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No IPTV servers could be extracted from the provided sources.'})}\n\n"
        return

    total = len(all_servers)
    yield f"data: {json.dumps({'type': 'parsed_servers', 'count': total, 'message': f'Parsed {total} unique IPTV servers. Starting audit...'})}\n\n"

    # Parallelism tuning (allow up to 50 concurrent audits for extreme speed)
    concurrency_limit = max(1, min(payload.concurrency or config.MAX_CONCURRENT_CHECKS, 50))
    semaphore = asyncio.Semaphore(concurrency_limit)
    completed_count = 0
    dead_host_cache: Dict[str, str] = {}

    audit_limits = httpx.Limits(max_keepalive_connections=concurrency_limit * 2, max_connections=concurrency_limit * 3)
    async with httpx.AsyncClient(verify=False, limits=audit_limits) as audit_client:

        async def worker(srv: IPTVServer) -> Optional[AuditResult]:
            nonlocal completed_count
            if session.is_stopped:
                return None

            await session.wait_if_paused()
            if session.is_stopped:
                return None

            async with semaphore:
                if session.is_stopped:
                    return None
                res = await audit_iptv_server(
                    srv,
                    audit_client,
                    probe_stream=payload.probe_stream,
                    audit_mode=payload.audit_mode,
                    dead_host_cache=dead_host_cache,
                )
                completed_count += 1
                return res

        tasks = [asyncio.create_task(worker(s)) for s in all_servers]

        for coro in asyncio.as_completed(tasks):
            if session.is_stopped:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                yield f"data: {json.dumps({'type': 'audit_stopped', 'message': 'Audit stopped by user.'})}\n\n"
                return

            res = await coro
            if res is not None:
                data_dict = res.model_dump()
                data_dict["completed"] = completed_count
                data_dict["total"] = total
                yield f"data: {json.dumps({'type': 'server_result', 'data': data_dict})}\n\n"

    yield f"data: {json.dumps({'type': 'audit_complete', 'total': total, 'message': 'Audit completed successfully!'})}\n\n"


@app.post("/api/audit/stream")
async def api_audit_stream(payload: AuditRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    session = AuditSession(session_id)
    active_sessions[session_id] = session

    async def stream_wrapper():
        try:
            async for item in run_audit_stream(payload, session):
                yield item
        finally:
            active_sessions.pop(session_id, None)

    return StreamingResponse(
        stream_wrapper(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/stream/proxy")
async def proxy_live_stream(url: str):
    """
    Proxies live MPEG-TS / HLS stream from IPTV provider with redirect support.
    """
    if not url.startswith(("http://", "https://")):
        return Response(content="Invalid stream URL", status_code=400)

    req_headers = {
        "User-Agent": "VLC/3.0.18 LibVLC/3.0.18",
        "Accept": "*/*",
    }

    client = httpx.AsyncClient(verify=False, timeout=15.0, follow_redirects=True)

    async def stream_generator():
        try:
            async with client.stream("GET", url, headers=req_headers) as response:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Stream proxy closed: %s", e)
        finally:
            await client.aclose()

    return StreamingResponse(
        stream_generator(),
        media_type="video/mp2t",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/play/m3u")
async def download_single_stream_m3u(url: str, title: str = "Live Stream"):
    """
    Returns a small single-channel .m3u playlist file targeting this direct stream.
    When opened on the user's laptop/PC, VLC immediately opens and plays the channel.
    """
    clean_title = title.strip() or "Live Stream"
    content = f"#EXTM3U\n#EXTINF:-1,{clean_title}\n{url}\n"
    import re
    safe_filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', clean_title)[:40] or "channel"
    return Response(
        content=content,
        media_type="audio/x-mpegurl",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}.m3u"',
            "Content-Type": "audio/x-mpegurl; charset=utf-8",
        },
    )


@app.post("/api/export/csv")
async def export_csv(results: List[Dict[str, Any]]):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Host",
            "Username",
            "Status",
            "Working",
            "Max Connections",
            "Active Connections",
            "Expiration Date",
            "Expiration Info",
            "TV Channels",
            "Movies (VOD)",
            "Series",
            "Adult Channels",
            "Adult Content",
            "Stream Probe",
            "Latency (ms)",
            "M3U URL",
        ]
    )

    for r in results:
        writer.writerow(
            [
                r.get("host", ""),
                r.get("username", ""),
                r.get("status", ""),
                "Yes" if r.get("is_working") else "No",
                r.get("max_connections", 0),
                r.get("active_connections", 0),
                r.get("exp_date", ""),
                r.get("exp_countdown", ""),
                r.get("live_channels", 0),
                r.get("movies_vod", 0),
                r.get("series", 0),
                r.get("adult_channels", 0),
                r.get("adult_details", "No"),
                r.get("stream_probe", ""),
                r.get("latency_ms", 0),
                r.get("m3u_url", ""),
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=iptv_audit_results.csv"},
    )
