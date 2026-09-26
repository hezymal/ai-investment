from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from pypdf import PdfReader

from .network import Fetcher, SourceError


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.current, self.text_parts = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = dict(attrs).get("href")
            self.text_parts = []

    def handle_data(self, data):
        if self.current is not None:
            self.text_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current, " ".join(" ".join(self.text_parts).split())))
            self.current = None


def discover_links(html: str, base_url: str) -> list[dict]:
    parser = Links()
    parser.feed(html)
    found = {}
    for href, title in parser.links:
        url = urljoin(base_url, href)
        if urlsplit(url).scheme != "https":
            continue
        searchable = (url + " " + title).casefold()
        if any(word in searchable for word in [".pdf", ".xlsx", ".zip", "мсфо", "рсбу", "отчет", "отчёт", "ifrs", "report", "statement"]):
            found[url] = {"url": url, "title": title or urlsplit(url).path,
                          "period": None, "note": "Период и вид документа требуют проверки по содержимому."}
    return list(found.values())


def extract_pdf(content: bytes, max_pages: int = 500) -> dict:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise SourceError("Encrypted PDF: provide an unlocked copy")
        pages = [{"page": i + 1, "text": page.extract_text() or ""} for i, page in enumerate(reader.pages[:max_pages])]
        sparse = [p["page"] for p in pages if len(p["text"].strip()) < 30]
        return {"pages": pages, "total_pages": len(reader.pages), "truncated": len(reader.pages) > max_pages,
                "pages_needing_visual_review": sparse,
                "note": "Текст не подтверждает правильность таблиц. Проверьте строки, колонки, знаки и единицы по оригиналу. Для сканов нужен OCR/визуальный разбор."}
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(f"Cannot extract PDF: {type(exc).__name__}") from exc


class Documents:
    def __init__(self, root: Path, fetcher: Fetcher, registry: Path):
        self.root, self.fetcher, self.registry = root, fetcher, registry

    def issuers(self, query: str = "") -> list[dict]:
        data = json.loads(self.registry.read_text(encoding="utf-8"))
        custom = self.root / "issuers.json"
        if custom.exists():
            data += json.loads(custom.read_text(encoding="utf-8"))
        return [e for e in data if query.casefold() in " ".join([e["id"], e["name"], *e.get("aliases", [])]).casefold()]

    def discover(self, issuer_id: str, refresh: bool = False) -> dict:
        issuers = [e for e in self.issuers() if e["id"] == issuer_id]
        if len(issuers) != 1:
            raise ValueError("issuer id must resolve uniquely in the registry; use list_issuers")
        links, errors, sources = {}, [], []
        for url in issuers[0]["report_pages"]:
            try:
                r = self.fetcher.get(url, ttl=0 if refresh else 3600, max_bytes=5_000_000)
                sources.append(r.provenance())
                for link in discover_links(r.text(), r.url):
                    links[link["url"]] = link
            except SourceError as exc:
                errors.append({"url": url, "error": str(exc)})
        return {"issuer": issuers[0], "documents": list(links.values()), "sources": sources,
                "errors": errors, "complete": not errors and bool(links),
                "fallback": "Если нужного документа нет, используйте официальный URL или локальный файл; динамические страницы и CAPTCHA автоматически не обходятся."}

    def links_on_page(self, url: str) -> dict:
        r = self.fetcher.get(url, ttl=3600, max_bytes=5_000_000)
        links = discover_links(r.text(), r.url)
        return {"links": links[:200], "truncated": len(links) > 200,
                "source": r.provenance(), "note": "Links are document candidates; verify issuer, period and file type."}

    def download(self, url: str, period: str | None = None) -> dict:
        r = self.fetcher.get(url, ttl=0)
        if not r.content.startswith(b"%PDF-"):
            raise SourceError("URL must return a PDF, not an HTML page or archive; use manual upload for other formats")
        digest = hashlib.sha256(r.content).hexdigest()
        target = self.root / "documents" / digest
        target.mkdir(parents=True, exist_ok=True)
        pdf = target / "document.pdf"
        if not pdf.exists():
            pdf.write_bytes(r.content)
        metadata = {**r.provenance(), "period": period, "path": str(pdf.resolve())}
        # Receipt is immutable even if the same bytes are downloaded on another date.
        import uuid
        receipt = target / f"receipt-{uuid.uuid4().hex}.json"
        receipt.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**metadata, "receipt": str(receipt.resolve())}

    def extract_local(self, path: str, workspace: Path, start_page: int = 1, page_count: int = 30) -> dict:
        p = Path(path)
        if not p.is_absolute():
            p = workspace / p
        p = p.resolve()
        if not p.is_relative_to(workspace.resolve()):
            raise ValueError("copy the document into the workspace before extracting")
        if not 1 <= start_page or not 1 <= page_count <= 100:
            raise ValueError("start_page >= 1; page_count = 1..100")
        if p.stat().st_size > 30_000_000:
            raise ValueError("PDF exceeds 30 MB")
        content = p.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise SourceError("file is not a PDF")
        result = extract_pdf(content)
        result["pages"] = result["pages"][start_page - 1:start_page - 1 + page_count]
        result.update({"sha256": hashlib.sha256(content).hexdigest(), "path": str(p),
                       "retrieved_at": datetime.now(timezone.utc).isoformat(),
                       "next_page": start_page + page_count if start_page + page_count <= min(result["total_pages"], 500) else None})
        return result
