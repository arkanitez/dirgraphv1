# DirGraph

Directory enumeration with auto wordlist selection + graph visualization.

## Quick start
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000
```

## What it does
- Probes the target URL, infers stack hints (CMS/API/IIS) and **auto-selects** SecLists wordlists.
- Uses async, concurrent enumeration with **soft-404** detection.
- Streams **progress** via WebSocket.
- Draws a **graph** of found paths with status codes and issue hints (directory listing, sensitive paths, backups, etc.).

## Wordlists
On first run it fetches a **pinned** subset of SecLists (Discovery/Web-Content) at commit `617ecd9393ecd12925bde2467201c51e6baa7cdb`.
You can swap to fetch the entire repo by adjusting `ensure_seclists()` in `backend/wordlists.py`.

## Legal
Only enumerate targets you have permission to test.
