#!/bin/bash
# Quick start script for Red Hat AI Products Release Planner

set -e

echo "=========================================="
echo "Red Hat AI Products Release Planner - Quick Start"
echo "=========================================="
echo ""

# Check if JIRA_TOKEN is set
if [ -z "$JIRA_TOKEN" ]; then
    echo "❌ ERROR: JIRA_TOKEN environment variable not set"
    echo ""
    echo "Please set your JIRA Personal Access Token:"
    echo "  export JIRA_TOKEN='your-token-here'"
    echo ""
    echo "Get token from: https://issues.redhat.com/secure/ViewProfile.jspa"
    echo ""
    exit 1
fi

echo "✅ JIRA_TOKEN is set"
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: python3 not found"
    echo "Please install Python 3.11 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✅ Python $PYTHON_VERSION found"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt
echo "✅ Dependencies installed"
echo ""

# Generate release plan
echo "🤖 Generating release plan from JIRA..."
echo "   This may take 1-2 minutes..."
echo ""
python3 release_manager.py
echo ""

# Check if HTML was generated
if [ ! -f "release-manager.html" ]; then
    echo "❌ ERROR: release-manager.html was not generated"
    exit 1
fi

echo "✅ Release plan generated successfully!"
echo ""
echo "=========================================="
echo "Next steps:"
echo "=========================================="
echo ""
echo "Option 1: Start local server"
echo "  ./serve.sh"
echo "  Then open: http://localhost:8000/release-manager.html"
echo ""
echo "Option 2: Open file directly"
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  open release-manager.html"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "  xdg-open release-manager.html"
else
    echo "  Open release-manager.html in your browser"
fi
echo ""
echo "=========================================="
