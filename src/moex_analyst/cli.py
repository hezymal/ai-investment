import argparse
import json
from pathlib import Path
import sys

from .documents import Documents
from .finance import BondInput, EquityInput, bond_analytics, compare_bonds, equity_analytics
from .history import History, local_root
from .metrics import all_calculations
from .models import Analysis
from .moex import Moex
from .network import Fetcher, SourceError
from .watchlist import Watchlist


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description="Локальная аналитика компаний МосБиржи")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema")
    for command in ["validate", "save", "bond", "equity", "compare-bonds"]:
        p = sub.add_parser(command)
        p.add_argument("file")
        if command == "save":
            p.add_argument("--no-charts", action="store_true")
    p = sub.add_parser("history")
    p.add_argument("--query", default="")
    p = sub.add_parser("show")
    p.add_argument("id")
    p = sub.add_parser("compare")
    p.add_argument("older")
    p.add_argument("newer")
    p = sub.add_parser("search")
    p.add_argument("query")
    p = sub.add_parser("security")
    p.add_argument("secid")
    p = sub.add_parser("reports")
    p.add_argument("issuer")
    p = sub.add_parser("extract")
    p.add_argument("file")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--count", type=int, default=30)
    sub.add_parser("watch-list")
    sub.add_parser("watch-check")
    p = sub.add_parser("watch-add")
    p.add_argument("issuer")
    p = sub.add_parser("watch-ack")
    p.add_argument("event", type=int)
    p.add_argument("analysis")
    args = parser.parse_args()
    root = local_root(args.workspace)
    history, fetcher = History(root), Fetcher(root)
    docs = Documents(root, fetcher, args.workspace / "config" / "issuers.json")
    try:
        match args.command:
            case "schema": result = Analysis.model_json_schema()
            case "validate": result = {"valid": True, "calculations": all_calculations(Analysis.model_validate(load(args.file)))}
            case "save": result = history.save(Analysis.model_validate(load(args.file)), not args.no_charts)
            case "history": result = history.list(args.query)
            case "show": result = history.read(args.id).model_dump(mode="json")
            case "compare": result = history.compare(args.older, args.newer)
            case "bond": result = bond_analytics(BondInput.model_validate(load(args.file)))
            case "equity": result = equity_analytics(EquityInput.model_validate(load(args.file)))
            case "compare-bonds": result = compare_bonds([BondInput.model_validate(b) for b in load(args.file)])
            case "search": result = Moex(fetcher).search(args.query)
            case "security": result = Moex(fetcher).security(args.secid)
            case "reports": result = docs.discover(args.issuer)
            case "extract": result = docs.extract_local(args.file, args.workspace, args.page, args.count)
            case "watch-add": result = Watchlist(root).add(args.issuer, docs)
            case "watch-list": result = Watchlist(root).list()
            case "watch-check": result = Watchlist(root).check(docs)
            case "watch-ack": result = Watchlist(root).acknowledge(args.event, args.analysis)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, SourceError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
