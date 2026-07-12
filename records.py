from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class Record:
    measurement: str
    tags: dict
    fields: dict
    time: datetime


def _days_to_departure(depart_date: str, now: datetime) -> int:
    dep = date.fromisoformat(depart_date)
    return (dep - now.date()).days


def airline_to_record(route: dict, cfg: dict, airline: str, price: int, now: datetime) -> Record:
    """One point per (route, airline): that airline's cheapest fare for the route."""
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f'{route["origin"]}-{route["destination"]}'),
            "origin": route["origin"],
            "destination": route["destination"],
            "trip": route.get("trip", "one-way"),
            "currency": cfg.get("currency", "TRY"),
            "airline": airline,
        },
        fields={
            "price": int(price),
            "days_to_departure": _days_to_departure(route["depart_date"], now),
        },
        time=now,
    )
