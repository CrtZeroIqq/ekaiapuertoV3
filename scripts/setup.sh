#!/bin/bash
# EKAIA Puerto - Initial Setup Script

set -e

echo "? Setting up EKAIA Puerto..."

# Check Python version
MIN_PYTHON="3.10"
RECOMMENDED_PYTHON="3.11"
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)

if (( $(echo "$PYTHON_VERSION < $MIN_PYTHON" | bc -l) )); then
    echo "? Python $MIN_PYTHON or higher required. Found: $PYTHON_VERSION"
    exit 1
fi

if (( $(echo "$PYTHON_VERSION < $RECOMMENDED_PYTHON" | bc -l) )); then
    echo "??  Python $RECOMMENDED_PYTHON+ recomendado. Continuando con $PYTHON_VERSION..."
else
    echo "? Python version: $PYTHON_VERSION"
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "? Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
echo "??  Upgrading pip..."
pip install --upgrade pip

# Install PyTorch with CUDA 12.4
echo "? Installing PyTorch with CUDA 12.4..."
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# Install other requirements
echo "? Installing dependencies..."
pip install -r requirements.txt

# Create .env if not exists
if [ ! -f .env ]; then
    echo "? Creating .env from template..."
    cp .env.example .env
    echo "??  Please edit .env with your configuration"
fi

# Create necessary directories
echo "? Creating directories..."
mkdir -p logs
mkdir -p models

# ------------------------------
#  SKIP DOCKER MYSQL
# ------------------------------
echo "??  Using system MySQL — skipping Docker MySQL setup."

# Initialize database
echo "? Initializing database using system MySQL..."
source .env

python3 -c "
import asyncio
from app.config import get_settings
from app.models import DatabaseManager

async def init():
    settings = get_settings()
    db = DatabaseManager(settings.database_url)
    await db.init_db()
    print('? Database initialized')

asyncio.run(init())
"

echo ""
echo "? Setup complete!"
echo ""
echo "? Next steps:"
echo "1. Edit .env with your camera URLs and credentials"
echo "2. Place your YOLO model at: \${YOLO_MODEL_PATH}"
echo "3. Run: bash scripts/start.sh"
echo ""
