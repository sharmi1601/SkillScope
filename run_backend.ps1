# Boot the FastAPI backend on Windows.
# Usage: .\run_backend.ps1
Param([int]$Port = 8000)
Set-Location -Path $PSScriptRoot
uvicorn src.api:app --reload --port $Port
