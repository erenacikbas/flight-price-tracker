#!/usr/bin/env python3
"""Flight price logger: cheapest fare per departure date (Travelpayouts) -> InfluxDB.

Runs as a Kubernetes CronJob every 15 minutes. One /v1/prices/calendar call per
route returns the cheapest fare per day; we keep the dates inside the configured
window and write one point per (route, depart_date).
Exit codes: 0 = ok, 2 = hard failure (a route errored or returned no dates in range).
"""
import json
import os
import sys
from datetime import datetime, timezone, date, timedelta

from travelpayouts_fetch import fetch_calendar
from records import date_to_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dates_in_window(route: dict) -> set:
    """Set of YYYY-MM-DD strings the route wants (from date_range or depart_date)."""
    rng = route.get("date_range")
    if rng:
        start, end = date.fromisoformat(rng["start"]), date.fromisoformat(rng["end"])
        out, d = set(), start
        while d <= end:
            out.add(d.isoformat()); d += timedelta(days=1)
        return out
    return {route["depart_date"]} if route.get("depart_date") else set()


def collect(cfg: dict, fetch=fetch_calendar, now=None):
    now = now or datetime.now(timezone.utc)
    records, hard_failures = [], 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        rcfg = {**cfg, **{k: route[k] for k in ("trip",) if k in route}}
        try:
            calendar = fetch(route["origin"], route["destination"], rcfg)
        except Exception as e:
            print(f"  ERROR {rid}: {e}", file=sys.stderr)
            hard_failures += 1
            continue
        window = dates_in_window(route)
        hits = {d: info for d, info in calendar.items() if d in window}
        if not hits:
            print(f"  {rid}: no cached fares in the target window "
                  f"({len(calendar)} dates available overall)", file=sys.stderr)
        for d in sorted(hits):
            info = hits[d]
            print(f"  {rid} {d}: {info['price']} {cfg.get('currency','TRY')} {info['airline']} stops={info['stops']}")
            records.append(date_to_record(route, cfg, d, info, now))
    return records, hard_failures


def main() -> int:
    cfg = load_config()
    records, hard_failures = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {hard_failures} hard failure(s).")
    return 2 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
