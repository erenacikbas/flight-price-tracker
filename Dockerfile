FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Apply the fast-flights parser guard (temporary; pinned to ==3.0.2).
COPY scripts/patch_fast_flights.py scripts/patch_fast_flights.py
RUN python scripts/patch_fast_flights.py
COPY records.py flight_fetch.py influx_writer.py logger.py routes.json ./
ENTRYPOINT ["python", "logger.py"]
