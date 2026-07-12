from datetime import datetime, timezone
from records import Record
from influx_writer import build_point, influx_config_from_env

def test_build_point_encodes_tags_fields_time():
    rec = Record(
        measurement="flight_price",
        tags={"route_id": "IST-DPS", "currency": "EUR", "price_level": "typical"},
        fields={"price": 468, "num_options": 35, "cheapest_airline": "Qatar Airways",
                "days_to_departure": 106},
        time=datetime(2026, 7, 12, 18, 0, tzinfo=timezone.utc),
    )
    line = build_point(rec).to_line_protocol()
    assert line.startswith("flight_price,")
    assert "route_id=IST-DPS" in line
    assert "price_level=typical" in line
    assert "price=468i" in line          # integer field
    assert 'cheapest_airline="Qatar Airways"' in line

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("INFLUXDB_URL", "http://influxdb.flight-tracker:8086")
    monkeypatch.setenv("INFLUXDB_TOKEN", "tok")
    monkeypatch.setenv("INFLUXDB_ORG", "flights")
    monkeypatch.setenv("INFLUXDB_BUCKET", "flight_prices")
    cfg = influx_config_from_env()
    assert cfg == {"url": "http://influxdb.flight-tracker:8086", "token": "tok",
                   "org": "flights", "bucket": "flight_prices"}

def test_write_records_empty_opens_no_connection(monkeypatch):
    import influx_writer
    opened = {"n": 0}
    class BoomClient:
        def __init__(self, *a, **k):
            opened["n"] += 1
    monkeypatch.setattr(influx_writer, "InfluxDBClient", BoomClient)
    n = influx_writer.write_records([], {"url": "u", "token": "t", "org": "o", "bucket": "b"})
    assert n == 0
    assert opened["n"] == 0  # no client constructed for an empty batch


def test_write_records_writes_points(monkeypatch):
    import influx_writer
    from records import Record
    from datetime import datetime, timezone
    calls = {}
    class FakeWriteApi:
        def write(self, bucket=None, record=None):
            calls["bucket"] = bucket
            calls["count"] = len(record)
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def write_api(self, write_options=None): return FakeWriteApi()
    monkeypatch.setattr(influx_writer, "InfluxDBClient", FakeClient)
    rec = Record(measurement="flight_price", tags={"route_id": "IST-DPS"},
                 fields={"price": 468}, time=datetime(2026, 7, 12, tzinfo=timezone.utc))
    n = influx_writer.write_records([rec], {"url": "u", "token": "t", "org": "o", "bucket": "b"})
    assert n == 1
    assert calls["bucket"] == "b"
    assert calls["count"] == 1
