#!/usr/bin/env python3
"""Flight price logger: fetch cheapest fares per route and write them to InfluxDB.

Designed to run as a Kubernetes CronJob every 15 minutes.
Exit codes: 0 = ok (rows written or genuinely no itineraries),
            2 = hard failure (options existed but none were priced -> likely a
                parser/scrape breakage worth alerting on),
            1 = unexpected error.
"""
import json
import os
import sys
from datetime import datetime, timezone

from flight_fetch import fetch_cheapest
from records import route_to_record
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("ROUTES_PATH", os.path.join(HERE, "routes.json"))


def load_config(path=CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def collect(cfg: dict, fetch=fetch_cheapest, now=None):
    now = now or datetime.now(timezone.utc)
    records, hard_failures = [], 0
    for route in cfg.get("routes", []):
        rid = route.get("id", f'{route["origin"]}-{route["destination"]}')
        print(f"Querying {rid} ...")
        try:
            cheapest = fetch(route, cfg)
        except Exception as e:
            print(f"  ERROR for {rid}: {e}", file=sys.stderr)
            hard_failures += 1
            continue
        if cheapest.price is None:
            if cheapest.num_options > 0:
                # options existed but none were priced -> data path broke
                print(f"  HARD FAIL {rid}: {cheapest.num_options} options, none priced", file=sys.stderr)
                hard_failures += 1
            else:
                print(f"  no itineraries for {rid} (skipping)")
            continue
        print(f"  cheapest: {cheapest.price} {cfg.get('currency','EUR')} on {cheapest.airline}")
        records.append(route_to_record(route, cfg, cheapest, now))
    return records, hard_failures


def main() -> int:
    cfg = load_config()
    records, hard_failures = collect(cfg)
    written = write_records(records, influx_config_from_env())
    print(f"Wrote {written} point(s); {hard_failures} hard failure(s).")
    if hard_failures:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
