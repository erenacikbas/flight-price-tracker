from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class CheapestResult:
    price: int | None
    airline: str
    num_options: int
    price_level: str


@dataclass
class Record:
    measurement: str
    tags: dict
    fields: dict
    time: datetime


def _days_to_departure(depart_date: str, now: datetime) -> int:
    dep = date.fromisoformat(depart_date)
    return (dep - now.date()).days


def route_to_record(route: dict, cfg: dict, cheapest: CheapestResult, now: datetime) -> Record:
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f'{route["origin"]}-{route["destination"]}'),
            "origin": route["origin"],
            "destination": route["destination"],
            "trip": route.get("trip", "one-way"),
            "currency": cfg.get("currency", "EUR"),
            "price_level": cheapest.price_level or "unknown",
        },
        fields={
            "price": int(cheapest.price),
            "num_options": int(cheapest.num_options),
            "cheapest_airline": cheapest.airline or "",
            "days_to_departure": _days_to_departure(route["depart_date"], now),
        },
        time=now,
    )
