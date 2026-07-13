#!/usr/bin/env python3
"""Flight price logger: cheapest fare per airline per departure date (Google Flights
via a headless browser). Sweeps the route's date range using one browser; writes one
point per (route, depart_date, airline). Under-rendered/failed dates are skipped this
run (fill next run); only a total wipeout is a hard failure.
Exit codes: 0 ok, 2 hard failure.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta

from records import airline_date_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def route_dates(route: dict) -> list:
    rng = route.get("date_range")
    if rng:
        start, end = date.fromisoformat(rng["start"]), date.fromisoformat(rng["end"])
        out, d = [], start
        while d <= end:
            out.append(d.isoformat()); d += timedelta(days=1)
        return out
    return [route["depart_date"]] if route.get("depart_date") else []


def collect(cfg: dict, fetch, now=None):
    """fetch(origin, destination, date) -> {airline: {price, stops}}."""
    now = now or datetime.now(timezone.utc)
    gap = float(cfg.get("date_gap_seconds", 1))
    records, attempted, succeeded = [], 0, 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        dates = route_dates(route)
        for i, d in enumerate(dates):
            attempted += 1
            try:
                per_airline = fetch(route["origin"], route["destination"], d)
            except Exception as e:
                print(f"  {rid} {d}: fetch error ({str(e)[:50]})", file=sys.stderr)
                per_airline = {}
            if not per_airline:
                print(f"  {rid} {d}: no fares this run", file=sys.stderr)
                continue
            succeeded += 1
            cheapest = min(v["price"] for v in per_airline.values())
            print(f"  {rid} {d}: {len(per_airline)} airlines, cheapest {cheapest} {cfg.get('currency','TRY')}")
            for airline, info in per_airline.items():
                records.append(airline_date_record(route, cfg, d, airline, info, now))
            if gap and i < len(dates) - 1:
                time.sleep(gap)
    return records, attempted, succeeded


def main() -> int:
    from flight_fetch import browser, fetch_date_with_retry
    cfg = load_config()
    with browser(cfg) as ctx:
        records, attempted, succeeded = collect(
            cfg, fetch=lambda o, d, day: fetch_date_with_retry(ctx, o, d, day, cfg))
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {succeeded}/{attempted} dates succeeded.")
    return 2 if attempted and succeeded == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
