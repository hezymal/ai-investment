"""Opt-in live-source check. Writes only the ignored cache and reports no market payloads."""
from datetime import date, timedelta
from pathlib import Path

from moex_analyst.documents import Documents
from moex_analyst.history import local_root
from moex_analyst.macro import key_rates
from moex_analyst.moex import Moex
from moex_analyst.network import Fetcher


def main():
    workspace = Path(__file__).resolve().parents[1]
    root = local_root(workspace)
    fetcher = Fetcher(root)
    api = Moex(fetcher)
    checks = {
        "ISS search": lambda: api.search("ROSN")["securities"],
        "ISS description": lambda: api.security("ROSN")["description"],
        "ISS quote": lambda: api.quote("ROSN", "shares", "TQBR")["securities"],
        "ISS candles": lambda: api.series("ROSN", "shares", "TQBR", "2025-09-01", "2025-09-10")["candles"],
        "ISS history": lambda: api.series("ROSN", "shares", "TQBR", "2025-09-01", "2025-09-10", "history")["history"],
        "ISS coupons": lambda: api.bond_schedule("SU26238RMFS4")["coupons"],
        "CBR key rate": lambda: key_rates(fetcher, (date.today() - timedelta(days=10)).isoformat(), date.today().isoformat())["rates"],
        "Issuer report links": lambda: Documents(root, fetcher, workspace / "config/issuers.json").discover("rostelecom", True)["documents"],
    }
    failed = 0
    for name, run in checks.items():
        try:
            data = run()
            if not data:
                raise RuntimeError("Empty result")
            print(f"PASS {name}: {len(data)} rows/links", flush=True)
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {exc}", flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
