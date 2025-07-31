#!/bin/bash

# Web Scraper Start Script
echo "🕷️  Starting Web Scraper API..."

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
fi

# Check if dependencies are installed
echo "🔍 Checking dependencies..."
python -c "import playwright" 2>/dev/null || {
    echo "❌ Playwright not found. Running setup..."
    ./setup.sh
}

# Set environment variables
export FLASK_ENV=production
export PLAYWRIGHT_BROWSERS_PATH=0

# Start the server
echo "🚀 Starting server on http://localhost:8000"
echo "📖 API Documentation: http://localhost:8000"
echo "🔧 Health Check: http://localhost:8000/health"
echo ""
echo "💡 To test the scraper:"
echo "   python test_scraper.py"
echo ""
echo "⚠️  Press Ctrl+C to stop the server"
echo ""

# Choose between development and production mode
if [ "$1" = "dev" ]; then
    echo "🔧 Starting in development mode..."
    python main.py
else
    echo "🏭 Starting in production mode with Gunicorn..."
    gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 --access-logfile - main:app
fi
