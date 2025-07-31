#!/bin/bash

echo "🔧 Installing Web Scraper Dependencies..."

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
echo "📦 Installing Playwright browsers..."
playwright install chromium

# Install system dependencies for Playwright (Ubuntu/Debian)
echo "🖥️  Installing system dependencies..."
playwright install-deps chromium

echo "✅ Setup complete!"
echo ""
echo "🚀 To start the server:"
echo "python main.py"
echo ""
echo "🔗 API will be available at: http://localhost:8000"
echo "📖 Usage: POST to /scrape with {\"url\": \"https://example.com\"}"
