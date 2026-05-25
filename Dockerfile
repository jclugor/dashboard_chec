FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PORT=8050
ENV API_PORT=8000
ENV DEBUG=false
ENV ENVIRONMENT=production
ENV DATA_DIR=/app/data
ENV OUTPUT_DIR=/tmp/outputs
ENV WEB_CONCURRENCY=1
ENV WEB_THREADS=2
ENV MODEL_BACKEND=mock
ENV CACHE_ENABLED=true
ENV LOG_LEVEL=INFO
ENV INFERENCE_HTTP_RETRIES=1
ENV INFERENCE_RETRY_BACKOFF_MS=250
ENV MAX_SUMMARY_POINTS=5000
ENV MAX_MAP_HTML_CHARS=8000000
ENV API_STARTUP_POLL_SECONDS=3
ENV API_KEEPALIVE_SECONDS=60
ENV API_STARTUP_MAX_ATTEMPTS=0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY run.py run_dash.py run_api.py wsgi.py ./

RUN mkdir -p /tmp/outputs

EXPOSE 8050
EXPOSE 8000

# Keep worker count conservative by default; each worker can duplicate dataset/model memory.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8050} --workers ${WEB_CONCURRENCY:-1} --threads ${WEB_THREADS:-2} --timeout 120 wsgi:server"]
