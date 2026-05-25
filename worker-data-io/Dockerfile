FROM python:3.11-slim
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Command is passed via docker-compose (celery -A tasks_api worker --concurrency=20)
