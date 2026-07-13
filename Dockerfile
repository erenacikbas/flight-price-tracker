# Playwright base image ships Chromium under /ms-playwright (the python pkg is pip-installed).
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
WORKDIR /app
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY records.py flight_fetch.py influx_writer.py logger.py routes.json ./
ENTRYPOINT ["python3", "logger.py"]
