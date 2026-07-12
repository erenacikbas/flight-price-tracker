"""One-time import of data/prices.csv history into InfluxDB. Idempotent:
InfluxDB overwrites points with identical measurement+tags+timestamp."""
import csv
import os
import sys
from datetime import datetime

from records import Record, _days_to_departure
from influx_writer import influx_config_from_env, write_records

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "data", "prices.csv")


def csv_rows_to_records(path=DEFAULT_CSV) -> list[Record]:
    records = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("cheapest_price"):
                continue
            ts = datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00"))
            records.append(Record(
                measurement="flight_price",
                tags={
                    "route_id": row["route_id"],
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "trip": row.get("trip", "one-way"),
                    "currency": row.get("currency", "EUR"),
                    "price_level": "unknown",
                },
                fields={
                    "price": int(row["cheapest_price"]),
                    "num_options": int(row.get("num_options") or 0),
                    "cheapest_airline": row.get("cheapest_airline", ""),
                    "days_to_departure": _days_to_departure(row["depart_date"], ts),
                },
                time=ts,
            ))
    return records


def main() -> int:
    recs = csv_rows_to_records()
    n = write_records(recs, influx_config_from_env())
    print(f"Backfilled {n} historical point(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
