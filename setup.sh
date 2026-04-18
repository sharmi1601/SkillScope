#!/usr/bin/env bash
# setup.sh — one-shot environment bootstrap for SkillScope.
#
# Run from the `skillscope/` directory:
#     bash setup.sh
#
# What this does:
#   1. Creates a fresh Python venv in ./venv
#   2. Activates it and upgrades pip
#   3. Installs everything from requirements.txt
#   4. Copies .env.example → .env if one doesn't already exist
#
# After this finishes, edit `.env` and paste your Groq API key, then run:
#     source venv/bin/activate
#     python -m src.pipeline --role data_analyst --sample 50

set -euo pipefail

PY=${PYTHON:-python3}

echo "→ Creating venv in ./venv using $($PY --version)"
$PY -m venv venv

# shellcheck disable=SC1091
source venv/bin/activate

echo "→ Upgrading pip"
pip install --quiet --upgrade pip

echo "→ Installing requirements.txt"
pip install --quiet -r requirements.txt

if [ ! -f .env ]; then
    echo "→ Creating .env from .env.example (edit it with your real Groq key!)"
    cp .env.example .env
else
    echo "→ .env already exists, leaving it alone"
fi

echo ""
echo "✓ Environment ready."
echo ""
echo "Next steps:"
echo "  1. Edit .env and set GROQ_API_KEY to your real key from console.groq.com"
echo "  2. source venv/bin/activate"
echo "  3. python -m src.pipeline --role data_analyst --sample 50"
