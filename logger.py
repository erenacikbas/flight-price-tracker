#!/usr/bin/env python3
"""Flight price logger: fetch cheapest fare per airline per route and write to InfluxDB.

Runs as a Kubernetes CronJob every 15 minutes. One point per (route, airline).
Exit codes: 0 = ok, 2 = hard failure (a route returned no priced airlines / errored —
likely the consent cookie expired or the scrape broke), 1 = unexpected error.
"""
import json
import os
import sys
from datetime import datetime, timezone

from flight_fetch import airline_prices
from records import airline_to_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect(cfg: dict, fetch=airline_prices, now=None):
    now = now or datetime.now(timezone.utc)
    records, hard_failures = [], 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        print(f"Querying {rid} ...")
        try:
            prices = fetch(route, cfg)
        except Exception as e:
            print(f"  ERROR for {rid}: {e}", file=sys.stderr)
            hard_failures += 1
            continue
        if not prices:
            print(f"  HARD FAIL {rid}: no priced airlines returned", file=sys.stderr)
            hard_failures += 1
            continue
        cur = cfg.get("currency", "TRY")
        cheapest = min(prices.values())
        print(f"  {len(prices)} airlines; cheapest {cheapest} {cur}")
        for airline, price in prices.items():
            records.append(airline_to_record(route, cfg, airline, price, now))
    return records, hard_failures


def main() -> int:
    cfg = load_config()
    records, hard_failures = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {hard_failures} hard failure(s).")
    return 2 if hard_failures else 0


if __name__ == "__main__":
    sys.exit(main())
