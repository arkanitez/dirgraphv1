import asyncio, random, string
from urllib.parse import urljoin
from typing import Callable, Dict, List, Optional, Tuple
import aiohttp

from .models import FoundItem
from . import analyzer

EventCb = Callable[[Dict], None]

def _rand_token(n=24):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))

async def initial_probe(session: aiohttp.ClientSession, base: str) -> Tuple[str, Dict[str,str]]:
    try:
        async with session.get(base, allow_redirects=True) as r:
            text = await r.text(errors="ignore")
            headers = {k: v for k, v in r.headers.items()}
            return text, headers
    except Exception:
        return "", {}

async def soft_404_baseline(session: aiohttp.ClientSession, base: str) -> Tuple[int, int]:
    bogus = urljoin(base, f"/{_rand_token(18)}/")
    try:
        async with session.get(bogus, allow_redirects=False) as r:
            body = await r.read()
            return r.status, len(body or b"")
    except Exception:
        return 404, 0

class DirEnumerator:
    def __init__(self, base: str, follow_redirects=False, max_concurrency=64, timeout=10,
                 exts_hint: Optional[List[str]]=None):
        self.base = base.rstrip("/")
        self.follow_redirects = follow_redirects
        self.sem = asyncio.Semaphore(max_concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.exts_hint = exts_hint or []

    async def _check_one(self, session: aiohttp.ClientSession, path: str) -> Tuple[str, Optional[FoundItem], Optional[str]]:
        url = urljoin(self.base + "/", path.lstrip("/"))
        try:
            async with self.sem:
                async with session.get(url, allow_redirects=self.follow_redirects) as r:
                    body = await r.read()
                    loc = r.headers.get("Location")
                    item = FoundItem(
                        url=url, path=path, status=r.status,
                        size=len(body) if body else None,
                        redirected_to=loc
                    )
                    snippet = (body[:2048] or b"").decode(errors="ignore")
                    issues = analyzer.analyze_item(path, r.status, snippet)
                    item.issues = issues
                    return path, item, snippet
        except Exception:
            return path, None, None

    async def run(self, candidates: List[str], on_event: EventCb, baseline: Tuple[int,int]) -> List[FoundItem]:
        found: List[FoundItem] = []
        tasks = []
        total = len(candidates)
        done = 0
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for path in candidates:
                plist = [path]
                for ext in self.exts_hint:
                    if not path.endswith(ext):
                        plist.append(path.rstrip("/") + ext)
                for p in plist:
                    tasks.append(asyncio.create_task(self._check_one(session, p)))

            for fut in asyncio.as_completed(tasks):
                _, item, snippet = await fut
                done += 1
                if item:
                    bl_status, bl_size = baseline
                    if bl_status == 200 and item.status == 200 and item.size is not None and bl_size:
                        if abs(item.size - bl_size) <= max(250, int(0.15 * bl_size)):
                            pass
                        else:
                            found.append(item)
                    else:
                        found.append(item)
                    if item.status in (200, 204, 301, 302, 401, 403):
                        on_event({"type":"found","item":item.model_dump()})
                on_event({"type":"progress","value": done/total})
        return found
