#!/bin/bash
# PaintOmics 4 startup script
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/PaintomicsServer"

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate paintomics4

# Start MongoDB if it is not running
if ! pgrep -x "mongod" > /dev/null; then
  echo "MongoDB is not running. Starting MongoDB..."
  mongod --fork --dbpath /home/leyls/github/mongodb_data --logpath /home/leyls/mongodb.log
  # Wait a bit for MongoDB to start
  sleep 2
fi

echo "Starting PaintOmics 4..."
echo "  MongoDB: localhost:27017"
echo "  Server:  http://localhost:8000"
echo "  Admin:   admin / admin"
echo ""

python src/launch_server.py
