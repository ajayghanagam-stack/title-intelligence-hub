FROM --platform=linux/amd64 python:3.12-slim

# Install system dependencies (including Playwright browser deps and Cairo for SVG)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libpq-dev \
    curl \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/

# Install Playwright browsers
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY . .

# Create storage directory
RUN mkdir -p /app/storage

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Production: use gunicorn with uvicorn workers
# Development: use uvicorn directly
CMD ["sh", "-c", "if [ \"$DEBUG\" = 'true' ]; then uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload; else gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 300; fi"]
