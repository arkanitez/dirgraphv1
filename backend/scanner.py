import asyncio, zipfile, io, os
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable, Any
import aiohttp

# Pinned SecLists commit
SECLISTS_COMMIT = "617ecd9393ecd12925bde2467201c51e6baa7cdb"

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
SECLISTS_DIR = DATA / "SecLists"
WEB_CONTENT_DIR = SECLISTS_DIR / "Discovery" / "Web-Content"

# First-run subset (expand if you want more)
WANTED_PATTERNS = [
    "directory-list-2.3-*.txt",
    "raft-*-directories.txt",
    "CMS/*.txt",
    "SVNDigger/cat/*/*.txt",
]

EventCb = Callable[[Dict[str, Any]], None]


async def ensure_seclists(on_event: Optional[EventCb] = None):
    """
    Ensure the SecLists Web-Content subtree exists locally.
    On first run, download the repo zip, stream progress, and extract only what we need.
    """
    if WEB_CONTENT_DIR.exists():
        if on_event:
            await on_event({"type": "stage", "stage": "seclists_cached"})
        return

    SECLISTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    tmp_zip = DATA / "seclists.repo.zip.part"
    zip_url = f"https://codeload.github.com/danielmiessler/SecLists/zip/{SECLISTS_COMMIT}"

    timeout = aiohttp.ClientTimeout(total=1800)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if on_event:
            await on_event({"type": "stage", "stage": "seclists_download_start"})
        async with session.get(zip_url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with tmp_zip.open("wb") as f:
                async for chunk in resp.content.iter_chunked(1 << 20):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if on_event and total:
                        await on_event({
                            "type": "stage",
                            "stage": "seclists_downloading",
                            "downloaded": downloaded,
                            "total": total
                        })

    if on_event:
        await on_event({"type": "stage", "stage": "seclists_extract_start"})

    with zipfile.ZipFile(tmp_zip, "r") as z:
        prefix = f"SecLists-{SECLISTS_COMMIT}/Discovery/Web-Content/"
        members = [m for m in z.infolist() if m.filename.startswith(prefix)]
        total_members = len(members) or 1
        for i, m in enumerate(members, 1):
            rel = m.filename[len(f"SecLists-{SECLISTS_COMMIT}/"):]
            target = SECLISTS_DIR / rel
            if m.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as f:
                    f.write(z.read(m))
            if on_event and (i % 50 == 0 or i == total_members):
                await on_event({
                    "type": "stage",
                    "stage": "seclists_extracting",
                    "done": i,
                    "total": total_members
                })

    try:
        tmp_zip.unlink()
    except Exception:
        pass

    if on_event:
        await on_event({"type": "stage", "stage": "seclists_ready"})


def index_wordlists() -> Dict[str, List[Path]]:
    """Scan Web-Content subtree and index wordlists by category."""
    catalog: Dict[str, List[Path]] = {"base": [], "raft": [], "cms": [], "svn": []}
    if not WEB_CONTENT_DIR.exists():
        return catalog
    for pat in WANTED_PATTERNS:
        for p in WEB_CONTENT_DIR.glob(pat):
            name = p.name.lower()
            posix = p.as_posix().lower()
            if name.startswith("directory-list"):
                catalog["base"].append(p)
            elif name.startswith("raft-") and "directories" in name:
                catalog["raft"].append(p)
            elif "/cms/" in posix:
                catalog["cms"].append(p)
            elif "/svndigger/" in posix:
                catalog["svn"].append(p)
    for k in catalog:
        catalog[k].sort()
    return catalog


def choose_wordlists(
    url: str,
    html: str,
    headers: Dict[str, str],
    catalog: Dict[str, List[Path]]
) -> List[Tuple[str, Path]]:
    """Heuristics to select lists based on headers/HTML hints."""
    hdr = {k.lower(): v.lower() for k, v in headers.items()}
    lower_html = (html or "").lower()
    picks: List[Tuple[str, Path]] = []

    def add(label, group, limit=2):
        for p in group[:limit]:
            picks.append((label, p))

    is_api = (
        "application/json" in hdr.get("content-type", "") or
        "swagger" in lower_html or "openapi" in lower_html
    )
    is_wp = "wp-content" in lower_html or "wp-includes" in lower_html
    is_drupal = "drupal.settings" in lower_html or "sites/all/modules" in lower_html
    is_joomla = "joomla" in lower_html

    add("base", catalog["base"], limit=2)
    if catalog["raft"]:
        add("raft", catalog["raft"], limit=1)
    if is_wp or is_drupal or is_joomla:
        add("cms", catalog["cms"], limit=3)
    if is_api:
        # keep it small for APIs
        picks = [p for p in picks if p[0] == "base"][:1] + picks

    # Deduplicate by path
    seen = set()
    final: List[Tuple[str, Path]] = []
    for label, path in picks:
        if path not in seen:
            final.append((label, path))
            seen.add(path)
    return final


def iter_candidates(paths: List[Tuple[str, Path]], cap: int) -> List[str]:
    """
    Read lines from chosen wordlists and build a unique, normalized list of paths.
    GUARANTEES: returns List[str] (never bytes), leading '/' enforced.
    """
    yielded = 0
    dedupe = set()
    for _, p in paths:
        try:
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if yielded >= cap:
                        return list(dedupe)
                    s = line.strip()
                    if isinstance(s, (bytes, bytearray)):
                        s = s.decode("utf-8", "ignore").strip()
                    if not s or str(s).startswith("#"):
                        continue
                    s = str(s)
                    if not s.startswith("/"):
                        s = "/" + s
                    if s not in dedupe:
                        dedupe.add(s)
                        yielded += 1
        except Exception:
            # ignore unreadable files
            continue
    return list(dedupe)
