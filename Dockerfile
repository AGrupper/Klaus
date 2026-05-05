# Entry point: uvicorn interfaces.web_server:app
# Cloud Run sets $PORT (default 8080). A single worker is required because
# ConversationManager is in-process — multiple workers would split per-user
# conversation history across processes.

FROM python:3.11-slim

# Build-time environment (keeps cache clean, prevents .pyc files)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps layer BEFORE copying source (so a source-only change doesn't re-install deps)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source (everything not excluded by .dockerignore)
COPY . .

# Non-root user for security
RUN useradd --no-create-home --uid 1000 --shell /bin/false klaus
USER klaus

EXPOSE 8080

# Single worker REQUIRED: ConversationManager is in-process; multiple workers
# split per-user conversation history across processes.
CMD ["sh", "-c", "uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
