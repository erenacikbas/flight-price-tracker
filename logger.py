#!/usr/bin/env python3
"""Flight price logger: cheapest fare per airline per departure date (Google Flights).

Runs as a Kubernetes CronJob. Sweeps the route's date range; for each date fetches
live Google fares (retrying through Google's "Loading results" shell) and writes one
point per (route, depart_date, airline). Dates that never load this run are skipped
(they retry next run) and do NOT fail the run; a fetch exception is a hard failure.
Exit codes: 0 ok, 2 hard failure.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta

from flight_fetch import airline_prices
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


def collect(cfg: dict, fetch=airline_prices, now=None):
    now = now or datetime.now(timezone.utc)
    gap = float(cfg.get("date_gap_seconds", 2))
    records, attempted, succeeded = [], 0, 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        dates = route_dates(route)
        for i, d in enumerate(dates):
            attempted += 1
            try:
                per_airline = fetch(route["origin"], route["destination"], d, cfg)
            except Exception as e:  # all attempts hit the loading shell / error this run
                print(f"  {rid} {d}: no fares this run ({str(e)[:40]})", file=sys.stderr)
                continue
            succeeded += 1
            cheapest = min(v["price"] for v in per_airline.values())
            print(f"  {rid} {d}: {len(per_airline)} airlines, cheapest {cheapest} {cfg.get('currency','TRY')}")
            for airline, info in per_airline.items():
                records.append(airline_date_record(route, cfg, d, airline, info, now))
            if gap and i < len(dates) - 1:
                time.sleep(gap)  # be gentle between dates
    return records, attempted, succeeded


def main() -> int:
    cfg = load_config()
    records, attempted, succeeded = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {succeeded}/{attempted} dates succeeded.")
    # Every date failing (attempted>0, none succeeded) => likely rate-limited/broken => red.
    return 2 if attempted and succeeded == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
