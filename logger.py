#!/usr/bin/env python3
"""Flight price logger: fetch cheapest offer per airline per departure date (Duffel).

Runs as a Kubernetes CronJob every 15 minutes. For each route, sweeps a range of
departure dates and writes one point per (route, date, airline) to InfluxDB.
Exit codes: 0 = ok, 2 = hard failure (a date returned no offers / errored), 1 = unexpected.
"""
import json
import os
import sys
from datetime import datetime, timezone, date, timedelta

from duffel_fetch import fetch_date
from records import airline_to_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def route_dates(route: dict) -> list:
    """Explicit list (depart_dates), a range (date_range: {start,end}), or single depart_date."""
    if route.get("depart_dates"):
        return list(route["depart_dates"])
    rng = route.get("date_range")
    if rng:
        start, end = date.fromisoformat(rng["start"]), date.fromisoformat(rng["end"])
        out, d = [], start
        while d <= end:
            out.append(d.isoformat())
            d += timedelta(days=1)
        return out
    return [route["depart_date"]] if route.get("depart_date") else []


def collect(cfg: dict, fetch=fetch_date, now=None):
    now = now or datetime.now(timezone.utc)
    records, hard_failures = [], 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        for d in route_dates(route):
            try:
                per_airline = fetch(route["origin"], route["destination"], d, cfg)
            except Exception as e:
                print(f"  ERROR {rid} {d}: {e}", file=sys.stderr)
                hard_failures += 1
                continue
            if not per_airline:
                print(f"  HARD FAIL {rid} {d}: no offers", file=sys.stderr)
                hard_failures += 1
                continue
            cheapest = min(o["price"] for o in per_airline.values())
            cur = next(iter(per_airline.values()))["currency"]
            print(f"  {rid} {d}: {len(per_airline)} airlines, cheapest {cheapest} {cur}")
            for info in per_airline.values():
                records.append(airline_to_record(route, cfg, d, info, now))
    return records, hard_failures


def main() -> int:
    cfg = load_config()
    records, hard_failures = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {hard_failures} hard failure(s).")
    return 2 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
