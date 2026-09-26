"""Check the actual Git publication set; never read private .local files."""
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, check=True, capture_output=True)
paths = set(result.stdout.decode("utf-8").split("\0")) - {""}
bad = []
private = {".local", ".venv", "data", "downloads", "reports", "output", "tmp", "__pycache__"}
patterns = [re.compile(r"gh[pousr]_[A-Za-z0-9]{25,}"), re.compile(r"sk-[A-Za-z0-9_-]{25,}"),
            re.compile(r"AKIA[0-9A-Z]{16}"), re.compile("-----BEGIN " + "(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")]
for name in sorted(paths):
    p = Path(name)
    if private.intersection(p.parts) or name == ".codex/config.toml" or (p.name.startswith(".env") and p.name != ".env.example") or p.suffix in {".pdf", ".sqlite3", ".db", ".pem", ".key"}:
        bad.append(f"Private/generated file in publication set: {name}")
        continue
    file = root / p
    if file.is_file() and file.stat().st_size < 2_000_000:
        try:
            content = file.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if any(pattern.search(content) for pattern in patterns):
            bad.append(f"Credential-like value in {name}; inspect locally (value not printed)")
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
print(f"Public file check passed: {len(paths)} files; private data excluded")
