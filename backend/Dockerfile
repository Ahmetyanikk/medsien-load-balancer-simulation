FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Selective COPY only — never backend/tests, backend/data, a local venv, or
# repository metadata. Destinations are absolute so this is independent of
# WORKDIR ordering below.
COPY provided/ /app/provided/
COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app

# Editable install is intentional and required, not a dev leftover:
# app/config.py derives BASE_DIR/PROVIDED_DIR/DATA_DIR from __file__, so the
# `app` package must keep being imported from this exact source path
# (/app/backend/app) at runtime. A regular `pip install` would copy it into
# site-packages instead, silently breaking that path contract. Runtime
# dependencies only — the [dev] extra (pytest, httpx) is never installed here.
RUN pip install --no-cache-dir -e /app/backend

RUN mkdir -p /app/backend/data

WORKDIR /app/backend

EXPOSE 8000

# No curl/wget in python:3.12-slim (Debian, no busybox) — use Python itself,
# which is already guaranteed present, instead of installing a package solely
# for health checking.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# --workers 1 is mandatory, not a default: the repository RLock (D-015) and
# simulation Lock (D-016) are process-local and cannot coordinate across
# worker processes.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
