from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urlencode

from .network import Fetcher, SourceError


class TableCells(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.parts, self.in_cell = [], [], [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        if tag == "td":
            self.in_cell, self.parts = True, []

    def handle_data(self, data):
        if self.in_cell:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td":
            self.row.append("".join(self.parts).strip())
            self.in_cell = False
        if tag == "tr" and self.row:
            self.rows.append(self.row)


def parse_key_rates(html: str) -> list[dict]:
    parser = TableCells()
    parser.feed(html)
    rates = []
    for row in parser.rows:
        if len(row) != 2:
            continue
        try:
            day = datetime.strptime(row[0], "%d.%m.%Y").date().isoformat()
            rate = float(row[1].replace(",", ".").replace("\xa0", "").replace(" ", ""))
            if not 0 <= rate < 1000:
                continue
            rates.append({"date": day, "rate_percent": rate})
        except ValueError:
            continue
    return sorted(rates, key=lambda r: r["date"])


def key_rates(fetcher: Fetcher, from_date: str, till_date: str) -> dict:
    first, last = date.fromisoformat(from_date), date.fromisoformat(till_date)
    if first > last:
        raise ValueError("from_date must precede till_date")
    url = "https://www.cbr.ru/hd_base/KeyRate/?" + urlencode({"UniDbQuery.Posted": "True", "UniDbQuery.From": first.strftime("%d.%m.%Y"), "UniDbQuery.To": last.strftime("%d.%m.%Y")})
    r = fetcher.get(url, ttl=3600, max_bytes=5_000_000)
    rates = [x for x in parse_key_rates(r.text()) if first.isoformat() <= x["date"] <= last.isoformat()]
    if not rates:
        raise SourceError("No CBR key-rate rows in the requested range; no rate was assumed")
    return {"rates": rates, "source": r.provenance(), "latest_observation": rates[-1]["date"]}
