#!/bin/bash
# PaintOmics 4 startup script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/PaintomicsServer"

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate paintomics4

echo "Starting PaintOmics 4..."
echo "  MongoDB: localhost:27017"
echo "  Server:  http://localhost:8000"
echo "  Admin:   admin / admin"
echo ""

python src/launch_server.py
