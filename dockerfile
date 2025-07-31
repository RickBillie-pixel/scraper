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
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers with explicit path
RUN mkdir -p /app/pw-browsers
RUN PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers playwright install chromium
RUN PLAYWRIGHT_BROWSERS_PATH=/app/pw-browsers playwright install-deps chromium

# Verify browser installation
RUN ls -la /app/pw-browsers/
RUN find /app/pw-browsers -name "chrome" -type f || echo "Chrome binary not found"

# Copy application code
COPY main.py .

# Create non-root user and fix permissions
RUN groupadd -r scraper && useradd -r -g scraper scraper
RUN chown -R scraper:scraper /app
USER scraper

# Expose port (Render uses PORT environment variable)
EXPOSE $PORT

# Start command
CMD gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 --preload main:app
