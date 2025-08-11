import asyncio, json, uuid
from pathlib import Path
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import EnumerateRequest
from .wordlists import ensure_seclists, index_wordlists, choose_wordlists, iter_candidates
from .scanner import DirEnumerator, initial_probe, soft_404_baseline

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(title="DirGraph")
app.mount("/static", StaticFiles(directory=str(FRONTEND), html=False), name="static")

@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")

JOBS: Dict[str, Dict] = {}

def _to_graph(base_url: str, items: List[dict]):
    nodes = [{"data":{"id":"root","label":base_url, "status":200}}]
    edges = []
    seen = {"root"}
    def node_id_for(path: str) -> str:
        return ("root" if path in ("", "/") else path.rstrip("/")) or "root"
    for it in items:
        path = it["path"]; np = node_id_for(path)
        if np not in seen:
            nodes.append({"data":{"id": np, "label": path, "status": it["status"], "url": it["url"], "issues":"; ".join(it.get("issues") or [])}})
            seen.add(np)
        parent = "root"
        if path and path != "/":
            if "/" in path.strip("/"):
                parent_path = "/" + "/".join(path.strip("/").split("/")[:-1])
                parent = node_id_for(parent_path)
                if parent not in seen:
                    nodes.append({"data":{"id": parent, "label": parent_path}}); seen.add(parent)
        edges.append({"data":{"id": f"{parent}->{np}", "source": parent, "target": np}})
    summary = {
        "total_tested": len(items),
        "ok_200": sum(1 for i in items if i["status"]==200),
        "forbidden_403": sum(1 for i in items if i["status"]==403),
        "auth_401": sum(1 for i in items if i["status"]==401),
        "redirects_30x": sum(1 for i in items if str(i["status"]).startswith("30")),
    }
    return {"nodes":nodes, "edges":edges, "summary":summary, "findings":items}

@app.post("/api/enumerate")
async def start_enumeration(req: EnumerateRequest):
    job_id = str(uuid.uuid4())
    q: asyncio.Queue = asyncio.Queue()
    JOBS[job_id] = {"queue": q}

    async def emit(ev): await q.put(ev)

    async def run():
        # SecLists (streamed progress)
        await ensure_seclists(on_event=emit)
        await emit({"type":"stage","stage":"indexing_lists"})
        catalog = index_wordlists()

        enumerator = DirEnumerator(
            req.url, follow_redirects=req.follow_redirects,
            max_concurrency=req.max_concurrency, timeout=req.timeout_seconds
        )

        await emit({"type":"stage","stage":"probing_target"})
        import aiohttp
        async with aiohttp.ClientSession() as session:
            html, headers = await initial_probe(session, req.url)

            await emit({"type":"stage","stage":"choosing_wordlists"})
            chosen = choose_wordlists(req.url, html, headers, catalog)

            await emit({"type":"stage","stage":"building_candidates"})
            candidates = iter_candidates(chosen, req.max_paths)

            hdr_low = {k.lower(): v.lower() for k,v in headers.items()}
            exts = []
            if "microsoft-iis" in hdr_low.get("server","") or "asp.net" in hdr_low.get("x-powered-by",""):
                exts = [".aspx", ".asp"]
            elif "php" in hdr_low.get("x-powered-by","") or "php" in (html or "").lower():
                exts = [".php"]

            await emit({"type":"meta","wordlists":[str(p) for _,p in chosen], "total_candidates": len(candidates), "exts": exts})
            await emit({"type":"stage","stage":"soft_404_baseline"})
            baseline = await soft_404_baseline(session, req.url)

        enumerator.exts_hint = exts
        await emit({"type":"stage","stage":"enumeration_started"})
        found_items = await enumerator.run(candidates, emit, baseline)

        filtered = [f.model_dump() for f in found_items if f.status in (200, 204, 301, 302, 401, 403)]
        graph = _to_graph(req.url, filtered)
        await emit({"type":"done","result": graph})
        await q.put(None)

    JOBS[job_id]["task"] = asyncio.create_task(run())
    return {"job_id": job_id}

@app.websocket("/ws/{job_id}")
async def ws_progress(ws: WebSocket, job_id: str):
    await ws.accept()
    if job_id not in JOBS:
        await ws.send_json({"type":"error","message":"unknown job"})
        await ws.close(); return
    q: asyncio.Queue = JOBS[job_id]["queue"]
    try:
        while True:
            ev = await q.get()
            if ev is None: break
            await ws.send_json(ev)
    except WebSocketDisconnect:
        pass
    finally:
        await ws.close()
        JOBS.pop(job_id, None)

@app.delete("/api/enumerate/{job_id}")
async def cancel(job_id: str):
    job = JOBS.get(job_id)
    if not job: raise HTTPException(status_code=404, detail="unknown job")
    task = job.get("task")
    if task: task.cancel()
    try:
        await job["queue"].put({"type":"canceled"})
        await job["queue"].put(None)
    except Exception:
        pass
    return {"status":"canceled"}
