FROM python:3.13-slim

WORKDIR /app

# Copy the lock file first for layer caching; --require-hashes rejects any file that doesn't match it
COPY backend/requirements.txt requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY backend/kroger_lookup/ kroger_lookup/
COPY backend/.env.example .env.example

# Web mode: no atlas/deals features
ENV WEB_MODE=true
ENV PORT=8000

EXPOSE 8000

# Run unprivileged; web mode writes nothing to disk (/api/setup is disabled)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app

CMD ["python", "-m", "kroger_lookup"]
