FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY records.py duffel_fetch.py influx_writer.py logger.py routes.json ./
ENTRYPOINT ["python", "logger.py"]
