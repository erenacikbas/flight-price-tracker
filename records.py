from dataclasses import dataclass
from datetime import datetime, date


@dataclass
class Record:
    measurement: str
    tags: dict
    fields: dict
    time: datetime


def _days_to_departure(depart_date: str, now: datetime) -> int:
    return (date.fromisoformat(depart_date) - now.date()).days


def booking_url(origin: str, destination: str, depart_date: str, marker: str, adults: int = 1) -> str:
    """Aviasales search deep-link with the affiliate marker (one-way).
    URL pattern: /search/{ORIGIN}{DDMM}{DEST}{PAX}?marker=..."""
    d = date.fromisoformat(depart_date)
    ddmm = f"{d.day:02d}{d.month:02d}"
    return f"https://www.aviasales.com/search/{origin}{ddmm}{destination}{adults}?marker={marker}"


def date_to_record(route: dict, cfg: dict, depart_date: str, info: dict, now: datetime) -> Record:
    """One point per (route, depart_date): the cheapest fare that day."""
    origin, destination = route["origin"], route["destination"]
    marker = str(cfg.get("marker", ""))
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f"{origin}-{destination}"),
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "airline": info.get("airline", "Unknown"),
            "currency": cfg.get("currency", "TRY").upper(),
        },
        fields={
            "price": int(info["price"]),
            "stops": int(info.get("stops", 0)),
            "days_to_departure": _days_to_departure(depart_date, now),
            "booking_url": booking_url(origin, destination, depart_date, marker, cfg.get("adults", 1)),
        },
        time=now,
    )
