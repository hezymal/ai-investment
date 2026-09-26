from datetime import date
import re
from urllib.parse import urlencode

from .network import Fetcher, SourceError

BASE = "https://iss.moex.com/iss/"
TERMS = "https://www.moex.com/a2193"


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", value):
        raise ValueError("invalid ISS identifier")
    return value


def rows(payload: dict, block: str) -> list[dict]:
    if block not in payload:
        raise SourceError(f"ISS response is missing block {block}")
    table = payload[block]
    try:
        return [dict(zip(table["columns"], row, strict=True)) for row in table["data"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError(f"Unexpected ISS schema in {block}") from exc


class Moex:
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def request(self, path: str, params: dict | None = None, ttl: int = 300) -> tuple[dict, dict]:
        url = BASE + path + ".json?" + urlencode({"iss.meta": "off", **(params or {})})
        r = self.fetcher.get(url, ttl=ttl)
        return r.json(), r.provenance()

    def search(self, query: str, start: int = 0) -> dict:
        if not query.strip() or not 0 <= start <= 100000:
            raise ValueError("query required; start must be 0..100000")
        data, source = self.request("securities", {"q": query, "start": start, "limit": 100}, 3600)
        found = rows(data, "securities")
        return {"securities": found, "next_start": start + len(found) if len(found) == 100 else None,
                "source": source, "note": "Выберите точный SECID/ISIN; поиск по названию может вернуть несколько эмитентов и выпусков."}

    def security(self, secid: str) -> dict:
        data, source = self.request(f"securities/{identifier(secid)}", ttl=3600)
        description = rows(data, "description")
        if not description:
            raise SourceError("Security not found")
        return {"description": description, "boards": rows(data, "boards"), "source": source}

    def quote(self, secid: str, market: str, board: str) -> dict:
        if market not in {"bonds", "shares"}:
            raise ValueError("market must be bonds or shares")
        path = f"engines/stock/markets/{market}/boards/{identifier(board)}/securities/{identifier(secid)}"
        data, source = self.request(path, ttl=60)
        description, quotes = rows(data, "securities"), rows(data, "marketdata")
        if not description:
            raise SourceError("Security not found on the selected board")
        return {"securities": description, "marketdata": quotes,
                "marketdata_version": rows(data, "marketdata_version") if "marketdata_version" in data else [],
                "source": source, "terms": TERMS,
                "note": "Возможна задержка. Время получения не равно времени сделки; смотрите UPDATETIME/SYSTIME/TRADINGSESSION. Нулевые/отсутствующие цены не заменять последними без явного указания."}

    def series(self, secid: str, market: str, board: str, start_date: str, end_date: str,
               kind: str = "candles", interval: int = 24, max_pages: int = 20) -> dict:
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if first > last or not 1 <= max_pages <= 100:
            raise ValueError("invalid dates or page bound")
        if market not in {"bonds", "shares"} or kind not in {"candles", "history"}:
            raise ValueError("unsupported market or series")
        if interval not in {1, 10, 60, 24, 7, 31, 4}:
            raise ValueError("unsupported candle interval")
        base = f"engines/stock/markets/{market}/boards/{identifier(board)}/securities/{identifier(secid)}"
        path = base + "/candles" if kind == "candles" else "history/" + base
        all_rows, sources, start = [], [], 0
        for _ in range(max_pages):
            data, source = self.request(path, {"from": first.isoformat(), "till": last.isoformat(), "start": start, "interval": interval}, 3600)
            page = rows(data, kind)
            sources.append(source)
            if not page:
                return {kind: all_rows, "truncated": False, "sources": sources}
            all_rows.extend(page)
            start += len(page)
            cursor_key = f"{kind}.cursor"
            if cursor_key in data:
                cursor = rows(data, cursor_key)
                if cursor and start >= cursor[0].get("TOTAL", float("inf")):
                    return {kind: all_rows, "truncated": False, "sources": sources}
        return {kind: all_rows, "truncated": True, "next_start": start, "sources": sources,
                "warning": "Ограничение страниц достигнуто; сократите диапазон дат."}

    def bond_schedule(self, secid: str, block: str = "coupons", start: int = 0) -> dict:
        if block not in {"coupons", "amortizations", "offers"} or start < 0:
            raise ValueError("invalid block or start")
        data, source = self.request(f"statistics/engines/stock/markets/bonds/bondization/{identifier(secid)}",
                                    {"iss.only": f"{block},{block}.cursor", "start": start, "limit": 100}, 3600)
        found = rows(data, block)
        cursor = rows(data, block + ".cursor") if block + ".cursor" in data else []
        next_start = start + len(found) if found and (not cursor or start + len(found) < cursor[0]["TOTAL"]) else None
        return {block: found, "cursor": cursor, "next_start": next_start, "source": source,
                "note": "null в будущих купонах не означает нулевой купон. Сверьте график с решением о выпуске; запросите все страницы и все три блока."}
