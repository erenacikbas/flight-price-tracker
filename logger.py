#!/usr/bin/env python3
"""Flight price logger: cheapest fare per airline per departure date, via flightlist.io
(Kiwi.com data). One HTTP call per route covers the whole date range; writes one point
per (route, depart_date, airline).
Exit codes: 0 ok, 2 hard failure (a route errored or returned nothing).
"""
import json
import os
import sys
from datetime import datetime, timezone, date, timedelta

from records import date_airline_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def route_window(route: dict) -> set:
    rng = route["date_range"]
    start, end = date.fromisoformat(rng["start"]), date.fromisoformat(rng["end"])
    out, d = set(), start
    while d <= end:
        out.add(d.isoformat()); d += timedelta(days=1)
    return out


def collect(cfg: dict, fetch, now=None):
    """fetch(route) -> {(depart_date, airline): {price, stops, origin, airline}}."""
    now = now or datetime.now(timezone.utc)
    records, attempted, succeeded = [], 0, 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        attempted += 1
        try:
            grouped = fetch(route)
        except Exception as e:
            print(f"  ERROR {rid}: {e}", file=sys.stderr)
            continue
        window = route_window(route)
        kept = {k: v for k, v in grouped.items() if k[0] in window}
        if not kept:
            print(f"  {rid}: no fares in window", file=sys.stderr)
            continue
        succeeded += 1
        cheapest = min(v["price"] for v in kept.values())
        dates = {k[0] for k in kept}
        print(f"  {rid}: {len(kept)} (date,airline) fares over {len(dates)} days, cheapest {cheapest} {cfg.get('currency','TRY')}")
        for (dep, _air), info in sorted(kept.items()):
            records.append(date_airline_record(route, cfg, dep, info, now))
    return records, attempted, succeeded


def main() -> int:
    from flightlist_fetch import search, cheapest_per_date_airline
    cfg = load_config()
    records, attempted, succeeded = collect(
        cfg, fetch=lambda route: cheapest_per_date_airline(search(route, cfg)))
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {succeeded}/{attempted} routes succeeded.")
    return 2 if attempted and succeeded == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
