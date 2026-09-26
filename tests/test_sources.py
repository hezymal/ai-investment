from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from pypdf import PdfWriter

from moex_analyst.documents import Documents, discover_links, extract_pdf
from moex_analyst.macro import parse_key_rates
from moex_analyst.moex import Moex, rows
from moex_analyst.network import Fetcher, Response, SourceError, public_url
from moex_analyst.watchlist import Watchlist


def response(value, url="https://iss.moex.com/test"):
    return Response(json.dumps(value).encode(), url, datetime.now(timezone.utc).isoformat(), "application/json")


class IssTests(unittest.TestCase):
    def test_columns_not_position_assumptions(self):
        self.assertEqual(rows({"x": {"columns": ["value", "name"], "data": [[None, "coupon"]]}}, "x"), [{"value": None, "name": "coupon"}])
        with self.assertRaises(SourceError):
            rows({}, "x")

    def test_candle_pagination_and_truncation(self):
        class Fake:
            def get(self, url, **kwargs):
                start = int(parse_qs(urlsplit(url).query)["start"][0])
                return response({"candles": {"columns": ["begin", "close"], "data": [[str(start), start]] if start < 3 else []}}, url)
        api = Moex(Fake())
        partial = api.series("TEST", "shares", "TQBR", "2025-01-01", "2025-02-01", max_pages=2)
        self.assertTrue(partial["truncated"])
        full = api.series("TEST", "shares", "TQBR", "2025-01-01", "2025-02-01")
        self.assertFalse(full["truncated"])
        self.assertEqual(len(full["candles"]), 3)

    def test_bad_identifier_and_missing_board_fail(self):
        with self.assertRaises(ValueError):
            Moex(None).security("../secret")
        class Empty:
            def get(self, url, **kwargs):
                return response({"securities": {"columns": [], "data": []}, "marketdata": {"columns": [], "data": []}})
        with self.assertRaises(SourceError):
            Moex(Empty()).quote("TEST", "shares", "TQBR")

    def test_bond_page_cursor_and_null_coupon(self):
        class Fake:
            def get(self, url, **kwargs):
                return response({"coupons": {"columns": ["value"], "data": [[None]]},
                                 "coupons.cursor": {"columns": ["INDEX", "TOTAL", "PAGESIZE"], "data": [[0, 2, 1]]}})
        r = Moex(Fake()).bond_schedule("TEST")
        self.assertIsNone(r["coupons"][0]["value"])
        self.assertEqual(r["next_start"], 1)


class NetworkTests(unittest.TestCase):
    def test_private_addresses_and_credentials_rejected(self):
        for url in ["http://public.example/", "https://user:password@public.example/", "https://public.example:8080/"]:
            with self.subTest(url=url), self.assertRaises(SourceError):
                public_url(url)
        with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(SourceError):
                public_url("https://public.example/")

    def test_cache_provenance_limit_and_403(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            if request.url.path == "/blocked":
                return httpx.Response(403)
            return httpx.Response(200, content=b"abcd", headers={"content-type": "text/plain"})
        real_client = httpx.Client
        with tempfile.TemporaryDirectory() as d, patch("moex_analyst.network.public_url"), patch(
                "moex_analyst.network.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler))):
            f = Fetcher(Path(d))
            first = f.get("https://test.example/data", ttl=300)
            second = f.get("https://test.example/data", ttl=300)
            self.assertTrue(second.cached)
            self.assertEqual(first.retrieved_at, second.retrieved_at)
            self.assertEqual(len(calls), 1)
            with self.assertRaises(SourceError):
                f.get("https://test.example/data", max_bytes=2)
            with self.assertRaises(SourceError):
                f.get("https://test.example/blocked")
            self.assertEqual(calls.count("https://test.example/blocked"), 1)

    def test_stale_cache_is_not_a_network_fallback(self):
        real_client = httpx.Client
        broken = False
        def handler(request):
            if broken:
                return httpx.Response(503)
            return httpx.Response(200, content=b"old")
        with tempfile.TemporaryDirectory() as d, patch("moex_analyst.network.public_url"), patch("moex_analyst.network.time.sleep"), patch(
                "moex_analyst.network.httpx.Client", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler))):
            f = Fetcher(Path(d))
            f.get("https://test.example/data", ttl=1)
            file = next((Path(d) / "cache").glob("*.json"))
            entry = json.loads(file.read_text())
            entry["retrieved_at"] = "2000-01-01T00:00:00+00:00"
            file.write_text(json.dumps(entry))
            broken = True
            with self.assertRaises(SourceError):
                f.get("https://test.example/data", ttl=1)


class DocumentTests(unittest.TestCase):
    def test_document_discovery_deduplicates_and_does_not_invent_period(self):
        found = discover_links('<a href="/report.pdf"><b>МСФО</b> 2025</a><a href="/report.pdf">Отчёт</a><a href="javascript:bad()">report</a>', "https://issuer.example/ir")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://issuer.example/report.pdf")
        self.assertIsNone(found[0]["period"])

    def test_blank_pdf_is_flagged_and_broken_pdf_fails(self):
        writer, stream = PdfWriter(), io.BytesIO()
        writer.add_blank_page(width=100, height=100)
        writer.write(stream)
        result = extract_pdf(stream.getvalue())
        self.assertEqual(result["pages_needing_visual_review"], [1])
        with self.assertRaises(SourceError):
            extract_pdf(b"not a PDF")

    def test_pdf_text_has_page_provenance(self):
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer, stream = PdfWriter(), io.BytesIO()
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 20 100 Td (Revenue 2025: 1300 million RUB - synthetic fixture) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
        writer.write(stream)
        result = extract_pdf(stream.getvalue())
        self.assertEqual(result["pages"][0]["page"], 1)
        self.assertIn("1300", result["pages"][0]["text"])

    def test_cbr_decimal_comma(self):
        html = '<table><tr><td>25.09.2026</td><td>14,00</td></tr><tr><td>header</td><td>rate</td></tr></table>'
        self.assertEqual(parse_key_rates(html), [{"date": "2026-09-25", "rate_percent": 14.0}])


class WatchlistTests(unittest.TestCase):
    def test_first_check_baseline_new_pending_persists_and_error_preserves_state(self):
        class FakeDocs:
            urls = ["https://issuer.example/old.pdf"]
            complete = True
            def issuers(self):
                return [{"id": "issuer"}]
            def discover(self, issuer, refresh=False):
                return {"documents": [{"url": u, "title": u} for u in self.urls], "complete": self.complete, "errors": []}
        with tempfile.TemporaryDirectory() as d:
            w, docs = Watchlist(Path(d)), FakeDocs()
            w.add("issuer", docs)
            self.assertEqual(w.check(docs)["pending"], [])
            docs.urls.append("https://issuer.example/new.pdf")
            self.assertEqual(len(w.check(docs)["pending"]), 1)
            self.assertEqual(len(w.check(docs)["pending"]), 1)
            docs.complete = False
            self.assertEqual(len(w.check(docs)["errors"]), 1)
            self.assertEqual(len(w.list()["pending"]), 1)
