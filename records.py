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


def booking_url(origin: str, destination: str, depart_date: str) -> str:
    """Stable Kiwi.com search deep-link (via the flightlist affiliate) for route+date."""
    return ("https://www.kiwi.com/deep?affilid=flightlistflightlistio&currency=TRY"
            f"&from={origin}&to={destination}&departure={depart_date}")


def date_airline_record(route: dict, cfg: dict, depart_date: str, info: dict, now: datetime) -> Record:
    """One point per (route, depart_date, airline): that airline's cheapest fare."""
    origin = info.get("origin") or route["origin"]
    destination = route["destination"]
    return Record(
        measurement="flight_price",
        tags={
            "route_id": route.get("id", f'{route["origin"]}-{destination}'),
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "airline": info["airline"],
            "airline_logo": info.get("logo", ""),
            "depart_time": info.get("depart_time", ""),
            "currency": cfg.get("currency", "TRY").upper(),
            "booking_url": booking_url(origin, destination, depart_date),
        },
        fields={
            "price": int(info["price"]),
            "stops": int(info.get("stops", 0)),
            "days_to_departure": _days_to_departure(depart_date, now),
            "duration_min": int(info.get("duration_min", 0)),
            "bag_price": int(info.get("bag_price", 0)),
        },
        time=now,
    )
