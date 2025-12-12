#!/bin/bash
# EKAIA Puerto - Production Start Script (LOCAL MYSQL)

set -e

echo "🚀 Starting EKAIA Puerto..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "📝 Please copy .env.example to .env and configure it"
    exit 1
fi

# Load environment
source .env

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "🐍 Python version: $PYTHON_VERSION"

# Activate virtual environment (if exists)
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
fi

# --------------------------
# SKIP DOCKER MYSQL
# --------------------------
echo "🗄️  Using system MySQL — skipping Docker MySQL startup."

# Check MySQL connection (optional but useful)
echo "⏳ Checking MySQL connection..."
python3 - <<EOF
import pymysql
try:
    conn = pymysql.connect(
        host="${DB_HOST}",
        port=int("${DB_PORT}"),
        user="${DB_USER}",
        password="${DB_PASSWORD}",
        database="${DB_NAME}"
    )
    print("✅ MySQL connection OK")
except Exception as e:
    print("❌ MySQL connection failed:", e)
    exit(1)
EOF

# Run migrations (if alembic exists)

# Start Cloudflare Tunnel (if configured)
if [ ! -z "$CF_TUNNEL_TOKEN" ]; then
    echo "🌐 Starting Cloudflare Tunnel..."
    docker-compose up -d cloudflared
fi

# Start FastAPI
echo "🚀 Starting EKAIA API..."
python3 -m uvicorn app.main:app \
    --host ${API_HOST:-0.0.0.0} \
    --port ${API_PORT:-8000} \
    --workers 1 \
    --log-level info

echo "✅ EKAIA Puerto started successfully!"
echo "📊 Dashboard: http://localhost:${API_PORT:-8000}"
echo "📚 API Docs: http://localhost:${API_PORT:-8000}/docs"
