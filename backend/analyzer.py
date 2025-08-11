import re
from typing import List

SUSPICIOUS_DIRS = [
    "/.git", "/.svn", "/.hg", "/backup", "/backups", "/.env", "/config", "/configs",
    "/admin", "/phpmyadmin", "/wp-admin", "/server-status", "/.idea", "/.vscode"
]
BACKUP_PAT = re.compile(r"\.(zip|tar|tar\.gz|tgz|bak|old|rar)$", re.I)

def analyze_item(path: str, status: int, body_snippet: str) -> List[str]:
    issues: List[str] = []
    low = (body_snippet or "").lower()
    if status == 200:
        if "index of /" in low or ("parent directory" in low and "<title>index of" in low):
            issues.append("Directory listing enabled")
        if any(path.lower().startswith(d) for d in SUSPICIOUS_DIRS):
            issues.append("Sensitive path potentially exposed")
        if "phpinfo()" in low or "<h1>php info" in low:
            issues.append("phpinfo exposed")
    if status in (401, 403):
        if any(x in path.lower() for x in ("/admin", "/wp-admin", "/phpmyadmin")):
            issues.append("Restricted admin area (authorization required)")
    if BACKUP_PAT.search(path):
        issues.append("Backup/archive file exposed")
    return issues
