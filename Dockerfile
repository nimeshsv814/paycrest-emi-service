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

# ✅ Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# ✅ Upgrade core tools (fixes wheel vulnerability etc.)
RUN pip install --upgrade pip setuptools wheel

# ✅ Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# ✅ Install only required runtime libs + patch OS vulns
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# ✅ Create non-root user (secure)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

# ✅ Copy only required Python artifacts
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# ✅ Create uploads directory with proper ownership
RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app

# ✅ Copy application code
COPY --chown=appuser:appgroup app ./app

USER appuser

EXPOSE 8000

# ✅ Use production-ready uvicorn command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]