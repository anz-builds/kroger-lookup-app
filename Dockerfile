FROM python:3.13-slim

WORKDIR /app

# Copy requirements first for layer caching
COPY kroger-lookup/requirements-web.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY kroger-lookup/main.py .
COPY kroger-lookup/static/ static/
COPY kroger-lookup/.env.example .env.example

# Web mode: no curl_cffi needed, no atlas features
ENV WEB_MODE=true
ENV PORT=8000

EXPOSE 8000

CMD ["python", "main.py"]
