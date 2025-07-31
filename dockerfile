FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libgbm1 \
    libxss1 \
    xvfb \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set working directory
WORKDIR /app

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers with explicit path
RUN mkdir -p /app/pw-browsers
RUN PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers playwright install chromium
RUN PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers playwright install-deps chromium

# Verify browser installation and debug
RUN ls -la /app/pw-browsers/ || echo "Browser directory not found"
RUN find /app/pw-browsers -name "chrome*" -type f || echo "Chrome binary not found"
RUN du -sh /app/pw-browsers || echo "Could not get browser size"

# Copy application code
COPY main.py .

# Create non-root user and fix permissions
RUN groupadd -r scraper && useradd -r -g scraper scraper \
    && chown -R scraper:scraper /app \
    && chmod -R 755 /app

# Switch to non-root user
USER scraper

# Expose port (Render uses PORT environment variable)
EXPOSE ${PORT:-8000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start command with better configuration for Render
CMD gunicorn --bind 0.0.0.0:${PORT:-8000} \
    --workers 1 \
    --worker-class sync \
    --timeout 120 \
    --keep-alive 2 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --preload \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    main:app
