"""Bounded public HTTPS reads with provenance and an explicit, fresh-only cache."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx


class SourceError(RuntimeError):
    pass


def public_url(url: str) -> None:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in {None, 443}:
        raise SourceError("Only public HTTPS URLs without credentials are supported")
    try:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SourceError(f"DNS lookup failed for {p.hostname}") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise SourceError("Private, local and reserved addresses are not permitted")


@dataclass
class Response:
    content: bytes
    url: str
    retrieved_at: str
    content_type: str
    cached: bool = False

    def provenance(self) -> dict:
        return {"url": self.url, "retrieved_at": self.retrieved_at, "cached": self.cached,
                "sha256": hashlib.sha256(self.content).hexdigest()}

    def json(self):
        try:
            return json.loads(self.content)
        except (ValueError, UnicodeError) as exc:
            raise SourceError("Source did not return valid JSON") from exc

    def text(self):
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";", 1)[0].strip(' "')
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class Fetcher:
    def __init__(self, root: Path, timeout: float = 20):
        self.root = root / "cache"
        self.timeout = timeout

    def get(self, url: str, ttl: int = 0, max_bytes: int = 30_000_000) -> Response:
        key = hashlib.sha256(url.encode()).hexdigest()
        cached_file = self.root / f"{key}.json"
        if ttl and cached_file.exists():
            try:
                import base64
                entry = json.loads(cached_file.read_text(encoding="utf-8"))
                age = time.time() - datetime.fromisoformat(entry["retrieved_at"]).timestamp()
                content = base64.b64decode(entry["content"], validate=True)
                if 0 <= age < ttl and len(content) <= max_bytes:
                    return Response(content, entry["url"], entry["retrieved_at"], entry["content_type"], True)
            except (ValueError, KeyError, OSError):
                pass
        last_error = None
        for attempt in range(3):
            current = url
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False,
                                  headers={"User-Agent": "moex-analyst/0.1 (local research client)"}) as client:
                    for _ in range(6):
                        public_url(current)
                        with client.stream("GET", current) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                location = response.headers.get("location")
                                if not location:
                                    raise SourceError("Redirect without Location")
                                current = urljoin(current, location)
                                continue
                            response.raise_for_status()
                            chunks, size = [], 0
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > max_bytes:
                                    raise SourceError(f"Response exceeds {max_bytes} bytes")
                                chunks.append(chunk)
                            result = Response(b"".join(chunks), str(response.url), datetime.now(timezone.utc).isoformat(), response.headers.get("content-type", ""))
                            if ttl:
                                import base64
                                import uuid
                                self.root.mkdir(parents=True, exist_ok=True)
                                entry = {**result.provenance(), "content_type": result.content_type,
                                         "content": base64.b64encode(result.content).decode("ascii")}
                                temporary = self.root / f"{key}-{uuid.uuid4().hex}.tmp"
                                temporary.write_text(json.dumps(entry), encoding="utf-8")
                                temporary.replace(cached_file)
                            return result
                    raise SourceError("Too many redirects")
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code} from {urlsplit(current).hostname}"
                if exc.response.status_code not in {429, 500, 502, 503, 504}:
                    break
            except httpx.RequestError as exc:
                last_error = f"Network error from {urlsplit(current).hostname}: {type(exc).__name__}"
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        raise SourceError(f"{last_error}. Use a supplied document or retry later; stale cache was not substituted.")
