import os
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from records import Record


def influx_config_from_env() -> dict:
    return {
        "url": os.environ["INFLUXDB_URL"],
        "token": os.environ["INFLUXDB_TOKEN"],
        "org": os.environ["INFLUXDB_ORG"],
        "bucket": os.environ["INFLUXDB_BUCKET"],
    }


def build_point(record: Record) -> Point:
    p = Point(record.measurement)
    for k, v in record.tags.items():
        p = p.tag(k, v)
    for k, v in record.fields.items():
        p = p.field(k, v)
    return p.time(record.time, WritePrecision.S)


def write_records(records: list[Record], cfg: dict) -> int:
    if not records:
        return 0
    points = [build_point(r) for r in records]
    with InfluxDBClient(url=cfg["url"], token=cfg["token"], org=cfg["org"]) as client:
        client.write_api(write_options=SYNCHRONOUS).write(bucket=cfg["bucket"], record=points)
    return len(points)
