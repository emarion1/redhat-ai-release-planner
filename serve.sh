#!/bin/bash
# Simple local server for viewing the release manager dashboard

PORT="${1:-8000}"

echo "=========================================="
echo "Red Hat AI Products Release Planner - Local Server"
echo "=========================================="
echo ""
echo "Starting server on port $PORT..."
echo ""
echo "Access the dashboard at:"
echo "  http://localhost:$PORT/release-manager.html"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""
echo "=========================================="

python3 -m http.server $PORT
