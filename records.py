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
    """Google Flights deep-link for the exact route + date (where the tracked fares live)."""
    q = quote_plus(f"flights from {origin} to {destination} on {depart_date}")
    return f"https://www.google.com/travel/flights?q={q}"


def airline_date_record(route: dict, cfg: dict, depart_date: str, airline: str, info: dict, now: datetime) -> Record:
    """One point per (route, depart_date, airline): that airline's cheapest fare that day."""
    origin, destination = route["origin"], route["destination"]
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f"{origin}-{destination}"),
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "airline": airline,
            "currency": cfg.get("currency", "TRY").upper(),
            "booking_url": booking_url(origin, destination, depart_date),
        },
        fields={
            "price": int(info["price"]),
            "stops": int(info.get("stops", 0)),
            "days_to_departure": _days_to_departure(depart_date, now),
        },
        time=now,
    )
