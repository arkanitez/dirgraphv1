import asyncio, zipfile, io, os
from pathlib import Path
from typing import Dict, List, Tuple
import aiohttp

SECLISTS_COMMIT = "617ecd9393ecd12925bde2467201c51e6baa7cdb"
BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
SECLISTS_DIR = DATA / "SecLists"
WEB_CONTENT_DIR = SECLISTS_DIR / "Discovery" / "Web-Content"

WANTED_PATTERNS = [
    "directory-list-2.3-*.txt",
    "raft-*-directories.txt",
    "CMS/*.txt",
    "SVNDigger/cat/*/*.txt",
]

async def _download(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()

async def ensure_seclists():
    if WEB_CONTENT_DIR.exists():
        return
    os.makedirs(WEB_CONTENT_DIR, exist_ok=True)
    zip_url = f"https://codeload.github.com/danielmiessler/SecLists/zip/{SECLISTS_COMMIT}"
    blob = await _download(zip_url)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        prefix = f"SecLists-{SECLISTS_COMMIT}/Discovery/Web-Content/"
        for member in z.infolist():
            if not member.filename.startswith(prefix):
                continue
            rel = member.filename[len(f"SecLists-{SECLISTS_COMMIT}/"):]
            target = SECLISTS_DIR / rel
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as f:
                    f.write(z.read(member))

def index_wordlists() -> Dict[str, List[Path]]:
    catalog: Dict[str, List[Path]] = {"base": [], "raft": [], "cms": [], "svn": []}
    if not WEB_CONTENT_DIR.exists():
        return catalog
    for pat in WANTED_PATTERNS:
        for p in WEB_CONTENT_DIR.glob(pat):
            name = p.name.lower()
            if name.startswith("directory-list"):
                catalog["base"].append(p)
            elif name.startswith("raft-") and "directories" in name:
                catalog["raft"].append(p)
            elif "/cms/" in p.as_posix().lower():
                catalog["cms"].append(p)
            elif "/svndigger/" in p.as_posix().lower():
                catalog["svn"].append(p)
    catalog["base"].sort()
    catalog["raft"].sort()
    catalog["cms"].sort()
    catalog["svn"].sort()
    return catalog

def choose_wordlists(url: str, html: str, headers: Dict[str, str], catalog: Dict[str, List[Path]]) -> List[Tuple[str, Path]]:
    hdr = {k.lower(): v.lower() for k, v in headers.items()}
    lower_html = (html or "").lower()
    picks: List[Tuple[str, Path]] = []

    def add(label, group, limit=2):
        for p in group[:limit]:
            picks.append((label, p))

    is_api = "application/json" in hdr.get("content-type","") or "swagger" in lower_html or "openapi" in lower_html
    is_wp = "wp-content" in lower_html or "wp-includes" in lower_html
    is_drupal = "drupal.settings" in lower_html or "sites/all/modules" in lower_html
    is_joomla = "joomla" in lower_html
    is_iis = "microsoft-iis" in hdr.get("server","") or "asp.net" in hdr.get("x-powered-by","")

    add("base", catalog["base"], limit=2)
    if catalog["raft"]:
        add("raft", catalog["raft"], limit=1)

    if is_wp or is_drupal or is_joomla:
        add("cms", catalog["cms"], limit=3)

    if is_api:
        picks = [p for p in picks if p[0] == "base"][:1] + picks

    # dedupe
    seen = set()
    final = []
    for label, path in picks:
        if path not in seen:
            final.append((label, path))
            seen.add(path)
    return final

def iter_candidates(paths: List[Path], cap: int) -> List[str]:
    yielded = 0
    dedupe = set()
    for _, p in paths:
        try:
            with p.open("r", errors="ignore") as f:
                for line in f:
                    if yielded >= cap: return list(dedupe)
                    s = line.strip()
                    if not s or s.startswith("#"): continue
                    if not s.startswith("/"):
                        s = "/" + s
                    if s not in dedupe:
                        dedupe.add(s)
                        yielded += 1
        except Exception:
            continue
    return list(dedupe)
