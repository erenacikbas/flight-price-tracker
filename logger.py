#!/usr/bin/env python3
"""Flight price logger.

Reads routes.json, queries Google Flights (via fast-flights) for each route,
and appends the cheapest fare to data/prices.csv.

Designed to be run on a schedule (e.g. GitHub Actions every 15 minutes).
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

import fast_flights as ff

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "routes.json")
DATA_DIR = os.path.join(HERE, "data")
CSV_PATH = os.path.join(DATA_DIR, "prices.csv")

FIELDNAMES = [
    "timestamp_utc",
    "route_id",
    "origin",
    "destination",
    "depart_date",
    "return_date",
    "trip",
    "cheapest_price",
    "currency",
    "cheapest_airline",
    "num_options",
]

MAX_ATTEMPTS = 3


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_query(route, currency, seat, adults):
    legs = [
        ff.FlightQuery(
            date=route["depart_date"],
            from_airport=route["origin"],
            to_airport=route["destination"],
        )
    ]
    trip = route.get("trip", "one-way")
    if trip == "round-trip":
        if not route.get("return_date"):
            raise ValueError(f"route {route['id']} is round-trip but has no return_date")
        legs.append(
            ff.FlightQuery(
                date=route["return_date"],
                from_airport=route["destination"],
                to_airport=route["origin"],
            )
        )
    return ff.create_query(
        flights=legs,
        trip=trip,
        seat=seat,
        passengers=ff.Passengers(adults=adults),
        currency=currency,
    )


def cheapest(result):
    """Return (price:int, airline:str, num_options:int) for the cheapest itinerary."""
    valid = [f for f in result if isinstance(f.price, int) and f.price > 0]
    if not valid:
        return None, None, len(result)
    best = min(valid, key=lambda f: f.price)
    airline = ", ".join(best.airlines) if best.airlines else ""
    return best.price, airline, len(result)


def query_route(route, currency, seat, adults):
    q = build_query(route, currency, seat, adults)
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = ff.get_flights(q)
            return cheapest(result)
        except Exception as e:  # network hiccup, transient scrape failure, etc.
            last_err = e
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {e}", file=sys.stderr)
            time.sleep(4 * attempt)
    raise last_err


def ensure_csv():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()


def main():
    cfg = load_config()
    currency = cfg.get("currency", "USD")
    seat = cfg.get("seat", "economy")
    adults = cfg.get("adults", 1)
    routes = cfg.get("routes", [])

    ensure_csv()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = []
    for route in routes:
        rid = route.get("id", f"{route['origin']}-{route['destination']}")
        print(f"Querying {rid} ...")
        try:
            price, airline, n = query_route(route, currency, seat, adults)
        except Exception as e:
            print(f"  ERROR for {rid}: {e}", file=sys.stderr)
            continue
        if price is None:
            print(f"  no priced options found for {rid} (checked {n} itineraries)")
            continue
        print(f"  cheapest: {price} {currency} on {airline} ({n} options)")
        rows.append(
            {
                "timestamp_utc": now,
                "route_id": rid,
                "origin": route["origin"],
                "destination": route["destination"],
                "depart_date": route.get("depart_date", ""),
                "return_date": route.get("return_date", ""),
                "trip": route.get("trip", "one-way"),
                "cheapest_price": price,
                "currency": currency,
                "cheapest_airline": airline,
                "num_options": n,
            }
        )

    if not rows:
        print("No rows collected this run.")
        return 0

    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerows(rows)
    print(f"Appended {len(rows)} row(s) to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
