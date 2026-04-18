# setup.ps1 — Windows/conda bootstrap for SkillScope.
#
# Run from the skillscope\ directory in PowerShell:
#     .\setup.ps1
#
# What this does:
#   1. Creates a conda env called `skillscope` on Python 3.11
#   2. Installs everything from requirements.txt into it
#   3. Copies .env.example -> .env if one doesn't already exist
#
# After this finishes:
#   conda activate skillscope
#   notepad .env                # paste your Groq key
#   python -m src.pipeline --role data_analyst --sample 50

$ErrorActionPreference = "Stop"
$EnvName = "skillscope"

Write-Host "-> Creating conda env '$EnvName' on Python 3.11"
conda create -n $EnvName python=3.11 -y

Write-Host "-> Installing requirements.txt into '$EnvName'"
# `conda run` runs a command inside the env without needing to `activate` it here.
conda run -n $EnvName pip install -r requirements.txt

if (-not (Test-Path .env)) {
    Write-Host "-> Creating .env from .env.example (edit it with your real Groq key!)"
    Copy-Item .env.example .env
} else {
    Write-Host "-> .env already exists, leaving it alone"
}

Write-Host ""
Write-Host "Environment ready."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. conda activate $EnvName"
Write-Host "  2. notepad .env     # paste your Groq key, save, close"
Write-Host "  3. python -m src.pipeline --role data_analyst --sample 50"
