# AgentVault backend (FastAPI + SQLite). Build from the repository root:
#   docker build -t agentvault-api .
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AGENTVAULT_ENVIRONMENT=production \
    AGENTVAULT_DATABASE_URL=sqlite:////data/agentvault.db \
    AGENTVAULT_SCENARIOS_DIR=/app/scenarios

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY scenarios /app/scenarios

# Run as an unprivileged user; only /data is writable.
RUN useradd --system --uid 10001 --home /nonexistent agentvault \
    && mkdir -p /data && chown agentvault /data \
    && rm -rf app/tests
USER agentvault
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=4).status == 200 else 1)"

# One worker: SQLite has a single writer and startup recovery assumes one process per database.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
