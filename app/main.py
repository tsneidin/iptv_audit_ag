import asyncio
import csv
import io
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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

app = FastAPI(title="IPTV Audit", version="1.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


class AuditRequest(BaseModel):
    input_text: str
    probe_stream: bool = True
    concurrency: int = 8


@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "default_port": config.PORT,
            "probe_streams_default": config.PROBE_STREAMS,
        },
    )


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "iptv-audit", "version": "1.0.0"}


async def run_audit_stream(payload: AuditRequest) -> AsyncGenerator[str, None]:
    """
    Generator that parses the input, fetches sources, decrypts pastes,
    audits servers concurrently, and yields SSE messages.
    """
    yield f"data: {json.dumps({'type': 'status', 'message': 'Extracting and decoding URLs...'})}\n\n"

    urls = extract_urls_from_input(payload.input_text)
    if not urls:
        # Check if the user pasted direct server text or M3U content directly
        direct_servers = extract_iptv_servers(payload.input_text)
        if not direct_servers:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No valid URLs, encoded strings, or IPTV credentials found in input.'})}\n\n"
            return
        all_servers = direct_servers
    else:
        yield f"data: {json.dumps({'type': 'extracted_urls', 'urls': urls, 'message': f'Found {len(urls)} URLs/sources to process.'})}\n\n"

        # Fetch contents of all URLs
        async with httpx.AsyncClient(verify=False, timeout=config.REQUEST_TIMEOUT) as client:
            all_servers: List[IPTVServer] = []
            seen_keys = set()

            for idx, url in enumerate(urls, 1):
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
                    yield f"data: {json.dumps({'type': 'warning', 'message': f'Failed to process {url}: {str(e)}'})}\n\n"

    if not all_servers:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No IPTV servers could be extracted from the provided sources.'})}\n\n"
        return

    total = len(all_servers)
    yield f"data: {json.dumps({'type': 'parsed_servers', 'count': total, 'message': f'Parsed {total} unique IPTV servers. Commencing audit...'})}\n\n"

    # Audit concurrency management
    concurrency_limit = max(1, min(payload.concurrency or config.MAX_CONCURRENT_CHECKS, 16))
    semaphore = asyncio.Semaphore(concurrency_limit)
    completed_count = 0

    async with httpx.AsyncClient(verify=False, timeout=config.REQUEST_TIMEOUT + config.PROBE_TIMEOUT) as audit_client:

        async def worker(srv: IPTVServer) -> AuditResult:
            nonlocal completed_count
            async with semaphore:
                res = await audit_iptv_server(srv, audit_client, probe_stream=payload.probe_stream)
                completed_count += 1
                return res

        # Run audits and yield results as they complete
        tasks = [asyncio.create_task(worker(s)) for s in all_servers]

        for coro in asyncio.as_completed(tasks):
            res: AuditResult = await coro
            data_dict = res.model_dump()
            data_dict["completed"] = completed_count
            data_dict["total"] = total
            yield f"data: {json.dumps({'type': 'server_result', 'data': data_dict})}\n\n"

    yield f"data: {json.dumps({'type': 'audit_complete', 'total': total, 'message': 'Audit completed successfully!'})}\n\n"


@app.post("/api/audit/stream")
async def api_audit_stream(payload: AuditRequest):
    return StreamingResponse(
        run_audit_stream(payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
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
