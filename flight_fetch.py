# flight_fetch.py
import os
import time
import sys
import fast_flights as ff
from fast_flights.integrations.base import FetchIntegration
from primp import Client
from records import CheapestResult

MAX_ATTEMPTS = 3
URL = "https://www.google.com/travel/flights"

# Known-good SOCS consent cookie (see Task 1 outcome). Datacenter IPs get Google's
# EU consent wall without it. Rotatable via cfg/env if Google ever invalidates it.
DEFAULT_SOCS_COOKIE = "SOCS=CAISHAgBEhJnd3NfMjAyNDA5MTAtMF9SQzEaAmVuIAEaBgiAo7C3Bg"


def resolve_cookie(cfg: dict) -> str:
    return cfg.get("google_socs_cookie") or os.environ.get("GOOGLE_SOCS_COOKIE") or DEFAULT_SOCS_COOKIE


class CookieFetch(FetchIntegration):
    """Fetch the flights page with the SOCS consent cookie set, so Google serves the
    real results page instead of the EU consent interstitial."""

    def __init__(self, cookie: str):
        self._cookie = cookie

    def fetch_html(self, q, /) -> str:
        client = Client(impersonate="chrome_145", impersonate_os="macos",
                        referer=True, cookie_store=True)
        params = q.params() if hasattr(q, "params") else {"q": q}
        return client.get(URL, params=params, headers={"cookie": self._cookie}).text


def _build_query(route: dict, cfg: dict):
    legs = [ff.FlightQuery(date=route["depart_date"],
                           from_airport=route["origin"], to_airport=route["destination"])]
    trip = route.get("trip", "one-way")
    if trip == "round-trip":
        if not route.get("return_date"):
            raise ValueError(f'route {route.get("id")} is round-trip but has no return_date')
        legs.append(ff.FlightQuery(date=route["return_date"],
                                   from_airport=route["destination"], to_airport=route["origin"]))
    return ff.create_query(
        flights=legs, trip=trip, seat=cfg.get("seat", "economy"),
        passengers=ff.Passengers(adults=cfg.get("adults", 1)),
        currency=cfg.get("currency", "EUR"),
    )


def select_cheapest(result) -> CheapestResult:
    items = list(result)
    valid = [f for f in items if isinstance(f.price, int) and f.price > 0]
    level = getattr(result, "current_price", "") or ""
    if not valid:
        return CheapestResult(price=None, airline="", num_options=len(items), price_level=level)
    best = min(valid, key=lambda f: f.price)
    airline = ", ".join(best.airlines) if getattr(best, "airlines", None) else ""
    return CheapestResult(price=best.price, airline=airline, num_options=len(items), price_level=level)


def fetch_cheapest(route: dict, cfg: dict, get_flights=None) -> CheapestResult:
    get_flights = get_flights or ff.get_flights
    q = _build_query(route, cfg)
    integration = CookieFetch(resolve_cookie(cfg))
    last_err = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return select_cheapest(get_flights(q, integration=integration))
        except Exception as e:  # transient scrape/network failure
            last_err = e
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {e}", file=sys.stderr)
            time.sleep(4 * attempt)
    raise last_err
