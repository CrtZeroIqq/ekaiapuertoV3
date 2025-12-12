#!/bin/bash
# EKAIA Puerto - Production Start Script (LOCAL MYSQL)

set -e

echo "🚀 Starting EKAIA Puerto..."

# Check .env
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "📝 Please create .env using .env.example"
    exit 1
fi

# Load environment
source .env

# Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "🐍 Python version: $PYTHON_VERSION"

# Activate venv
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
fi

# -------------------------------
# MySQL (System)
# -------------------------------
echo "🗄️  Using system MySQL — skipping Docker MySQL."

echo "⏳ Checking MySQL connection..."
python3 - <<EOF
import pymysql, sys
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
    sys.exit(1)
EOF

# -------------------------------
# Cloudflare Tunnel
# -------------------------------
if [ ! -z "$CF_TUNNEL_TOKEN" ]; then
    echo "🌐 Starting Cloudflare Tunnel for ekaia.seidev.cl..."
    docker-compose up -d cloudflared
    echo "🔗 Tunnel active → https://ekaia.seidev.cl"
else
    echo "⚠️  No Cloudflare token found. Túnel no iniciado."
fi

# -------------------------------
# Start FastAPI
# -------------------------------
echo "🚀 Starting EKAIA API..."
python3 -m uvicorn app.main:app \
    --host ${API_HOST:-0.0.0.0} \
    --port ${API_PORT:-8000} \
    --workers 1 \
    --log-level info
