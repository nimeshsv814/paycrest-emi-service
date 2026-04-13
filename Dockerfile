# # ── Stage 1: Install Python packages ──────────────────────────
# FROM python:3.11-slim AS builder

# WORKDIR /app

# # ✅ Install system dependencies (VERY IMPORTANT for many Python libs)
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     gcc \
#     libpq-dev \
#     && rm -rf /var/lib/apt/lists/*

# COPY requirements.txt .

# # ✅ Upgrade pip first
# RUN pip install --upgrade pip setuptools wheel

# # ✅ Install dependencies
# RUN pip install --no-cache-dir -r requirements.txt

# # ── Stage 2: Runtime ──────────────────────────────────────────
# FROM python:3.11-slim AS runtime

# ENV PYTHONDONTWRITEBYTECODE=1 \
#     PYTHONUNBUFFERED=1 \
#     PYTHONPATH=/app

# WORKDIR /app

# # Create non-root user
# RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# # Copy installed packages
# COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
# COPY --from=builder /usr/local/bin /usr/local/bin

# # Create uploads directory
# RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app/uploads

# # Copy app code
# COPY --chown=appuser:appgroup app ./app

# USER appuser

# EXPOSE 8000

# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 1: Builder ──────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# ✅ Install system dependencies + patch OS vulnerabilities
RUN apt-get update && apt-get upgrade -y && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ✅ Upgrade core Python tools (fix wheel vulnerability)
RUN pip install --upgrade pip setuptools wheel

# ✅ Install dependencies (force reinstall to remove vulnerable versions)
RUN pip install --no-cache-dir --upgrade --force-reinstall -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# ✅ Install only required runtime libs + patch OS vulnerabilities
RUN apt-get update && apt-get upgrade -y && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ✅ Create non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# ✅ Copy installed Python packages
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# ✅ Create app directories with proper permissions
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

# ✅ Copy application code
COPY --chown=appuser:appgroup app ./app

USER appuser

EXPOSE 8000

# ✅ Production-ready command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]