"""Fetch cheapest offer per airline per departure date from the Duffel API.

Duffel is a real flight API (reliable, no scraping/rate-limit games). For each
departure date we POST an offer request and keep the cheapest offer per airline,
with segment info and a booking link.
"""
import os
import urllib.error
import urllib.request
import json
import time

API = "https://api.duffel.com/air/offer_requests?return_offers=true"
MAX_ATTEMPTS = 3


def _token() -> str:
    return os.environ["DUFFEL_TOKEN"]


def _post(body: dict) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {_token()}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _duration_minutes(iso: str) -> int:
    """ISO-8601 duration like 'PT16H35M' -> minutes."""
    if not iso or not iso.startswith("PT"):
        return 0
    h = m = 0
    num = ""
    for ch in iso[2:]:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            h = int(num or 0); num = ""
        elif ch == "M":
            m = int(num or 0); num = ""
        else:
            num = ""
    return h * 60 + m


def _offer_info(offer: dict) -> dict:
    owner = offer.get("owner") or {}
    airline = owner.get("name") or owner.get("iata_code") or "Unknown"
    slices = offer.get("slices") or []
    segments = slices[0].get("segments", []) if slices else []
    stops = max(len(segments) - 1, 0)
    duration = _duration_minutes(slices[0].get("duration", "")) if slices else 0
    return {
        "airline": airline,
        "price": float(offer["total_amount"]),
        "currency": offer.get("total_currency", ""),
        "stops": stops,
        "duration_min": duration,
        "offer_id": offer.get("id", ""),
    }


def cheapest_per_airline(offers: list) -> dict:
    """{airline: offer_info} keeping the cheapest offer for each airline."""
    out = {}
    for offer in offers:
        try:
            info = _offer_info(offer)
        except (KeyError, TypeError, ValueError):
            continue
        a = info["airline"]
        if a not in out or info["price"] < out[a]["price"]:
            out[a] = info
    return out


def fetch_date(origin: str, destination: str, date: str, cfg: dict, post=None) -> dict:
    """Return {airline: offer_info} for one origin/destination/date."""
    post = post or _post
    body = {
        "data": {
            "slices": [{"origin": origin, "destination": destination, "departure_date": date}],
            "passengers": [{"type": "adult"}],
            "cabin_class": cfg.get("cabin", cfg.get("seat", "economy")),
        }
    }
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = post(body)
            offers = (resp.get("data") or {}).get("offers", [])
            return cheapest_per_airline(offers)
        except Exception as e:
            last_err = e
            time.sleep(3 * attempt)
    raise last_err
