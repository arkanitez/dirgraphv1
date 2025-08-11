import asyncio, random, string, traceback
from urllib.parse import urljoin as _urljoin
from typing import Callable, Dict, List, Optional, Tuple
import aiohttp

from .models import FoundItem
from . import analyzer

EventCb = Callable[[Dict], None]

def _rand_token(n=24) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))

def _to_text(x) -> str:
    """Coerce any bytes/bytearray/other into str safely."""
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", "ignore")
    return str(x)

def _safe_urljoin(base, path) -> str:
    """Always join as str; never mix bytes/str."""
    b = _to_text(base)
    p = _to_text(path)
    # urljoin expects a relative path (no accidental bytes), strip leading slashes handled by caller
    return _urljoin(b, p)

async def initial_probe(session: aiohttp.ClientSession, base: str) -> Tuple[str, Dict[str, str]]:
    try:
        async with session.get(_to_text(base), allow_redirects=True) as r:
            text = await r.text(errors="ignore")
            headers = {k: v for k, v in r.headers.items()}
            return text, headers
    except Exception:
        return "", {}

async def soft_404_baseline(session: aiohttp.ClientSession, base: str) -> Tuple[int, int]:
    bogus = _safe_urljoin(_to_text(base), f"/{_rand_token(18)}/")
    try:
        async with session.get(bogus, allow_redirects=False) as r:
            body = await r.read()
            return r.status, len(body or b"")
    except Exception:
        return 404, 0

class DirEnumerator:
    def __init__(
        self,
        base: str,
        follow_redirects: bool = False,
        max_concurrency: int = 64,
        timeout: int = 10,
        exts_hint: Optional[List[str]] = None,
    ):
        self.base = _to_text(base).rstrip("/")
        self.follow_redirects = follow_redirects
        self.sem = asyncio.Semaphore(max_concurrency)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.exts_hint = exts_hint or []

    async def _check_one(
        self, session: aiohttp.ClientSession, path: str
    ) -> Tuple[str, Optional[FoundItem], Optional[str]]:
        try:
            path = _to_text(path)
            url = _safe_urljoin(self.base + "/", path.lstrip("/"))

            async with self.sem:
                async with session.get(url, allow_redirects=self.follow_redirects) as r:
                    body = await r.read()
                    loc = r.headers.get("Location")
                    item = FoundItem(
                        url=url,
                        path=path,
                        status=r.status,
                        size=len(body) if body else None,
                        redirected_to=loc,
                    )
                    snippet = (body[:2048] or b"").decode(errors="ignore")
                    item.issues = analyzer.analyze_item(path, r.status, snippet)
                    return path, item, snippet

        except Exception:
            # Return None item so the caller can keep going; details reported by caller
            return _to_text(path), None, None

    async def run(
        self,
        candidates: List[str],
        on_event: EventCb,
        baseline: Tuple[int, int],
    ) -> List[FoundItem]:
        found: List[FoundItem] = []
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                tasks = []
                for path in candidates:
                    path = _to_text(path)  # harden again
                    plist = [path]
                    for ext in self.exts_hint:
                        ext = _to_text(ext)
                        if not path.endswith(ext):
                            plist.append(path.rstrip("/") + ext)
                    for p in plist:
                        tasks.append(asyncio.create_task(self._check_one(session, p)))

                total = len(tasks) or 1
                done_count = 0

                for fut in asyncio.as_completed(tasks):
                    try:
                        _, item, _ = await fut
                    except Exception:
                        # Extremely rare: task-level exception; report and continue
                        await on_event({"type": "error", "message": traceback.format_exc()})
                        item = None

                    done_count += 1

                    if item:
                        bl_status, bl_size = baseline
                        if (
                            bl_status == 200
                            and item.status == 200
                            and item.size is not None
                            and bl_size
                            and abs(item.size - bl_size) <= max(250, int(0.15 * bl_size))
                        ):
                            pass  # probable soft-404
                        else:
                            found.append(item)

                        if item.status in (200, 204, 301, 302, 401, 403):
                            await on_event({"type": "found", "item": item.model_dump()})

                    await on_event({"type": "progress", "value": done_count / total})

        except Exception:
            # Surface any unexpected error during run()
            await on_event({"type": "error", "message": traceback.format_exc()})
        return found
