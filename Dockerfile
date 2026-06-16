# Entry point: uvicorn interfaces.web_server:app
# Cloud Run sets $PORT (default 8080). A single worker is required because
# ConversationManager is in-process — multiple workers would split per-user
# conversation history across processes.

# --------------------------------------------------------------------------- #
# Stage 1: Build the Vite + React frontend (Phase 26 hub shell).              #
# Produces /frontend/dist, copied into the Python runtime image below.        #
# --------------------------------------------------------------------------- #
FROM node:20-slim AS frontend-builder
WORKDIR /frontend
# Deps layer first (npm ci needs the lockfile) so a source-only change
# doesn't re-install node_modules.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The Google Sign-In client ID is read by the frontend at BUILD time
# (import.meta.env.VITE_GOOGLE_CLIENT_ID in SignInPage.tsx) and baked into the
# bundle. It is a public value (OAuth client IDs are not secrets). Pass it at
# build with `--build-arg VITE_GOOGLE_CLIENT_ID=...`; without it, sign-in silently
# fails because the bundle ships an empty client_id.
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
RUN npm run build

# --------------------------------------------------------------------------- #
# Stage 2: Python runtime (unchanged from the original single-stage image).   #
# --------------------------------------------------------------------------- #
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

# Built frontend from Stage 1 (.dockerignore excludes frontend/dist +
# frontend/node_modules from the COPY . . above, so this is the only dist).
COPY --from=frontend-builder /frontend/dist ./frontend/dist

# Non-root user for security
RUN useradd --no-create-home --uid 1000 --shell /bin/false klaus
USER klaus

EXPOSE 8080

# Single worker REQUIRED: ConversationManager is in-process; multiple workers
# split per-user conversation history across processes.
CMD ["sh", "-c", "uvicorn interfaces.web_server:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
