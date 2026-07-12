from dataclasses import dataclass
from datetime import datetime, date
from urllib.parse import quote_plus


@dataclass
class Record:
    measurement: str
    tags: dict
    fields: dict
    time: datetime


def _days_to_departure(depart_date: str, now: datetime) -> int:
    return (date.fromisoformat(depart_date) - now.date()).days


def booking_url(origin: str, destination: str, depart_date: str) -> str:
    """A stable 'go book this' link (Google Flights deep link for the exact route+date)."""
    q = quote_plus(f"flights from {origin} to {destination} on {depart_date}")
    return f"https://www.google.com/travel/flights?q={q}"


def airline_to_record(route: dict, cfg: dict, depart_date: str, info: dict, now: datetime) -> Record:
    """One point per (route, depart_date, airline): that airline's cheapest offer."""
    origin, destination = route["origin"], route["destination"]
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f"{origin}-{destination}"),
            "origin": origin,
            "destination": destination,
            "cabin": cfg.get("cabin", cfg.get("seat", "economy")),
            "depart_date": depart_date,
            "airline": info["airline"],
            "currency": info.get("currency", ""),
        },
        fields={
            "price": float(info["price"]),
            "stops": int(info.get("stops", 0)),
            "duration_min": int(info.get("duration_min", 0)),
            "offer_id": info.get("offer_id", ""),
            "booking_url": booking_url(origin, destination, depart_date),
            "days_to_departure": _days_to_departure(depart_date, now),
        },
        time=now,
    )
