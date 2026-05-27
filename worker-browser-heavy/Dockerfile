FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Ensure browsers are installed
RUN playwright install chromium
COPY . .
# Command is passed via docker-compose (celery -A tasks_browser worker -P solo --max-tasks-per-child=10)
