# Built from the repo root (docker-compose.yml), because POST /query runs the agent in model/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app:/app/model
WORKDIR /app

COPY backend/requirements.txt requirements.txt
COPY model/requirements.txt model/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r model/requirements.txt

COPY backend/app ./app
COPY backend/config ./config
COPY model/agent ./model/agent
COPY model/prompts ./model/prompts

RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
