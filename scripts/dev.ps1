# DARK POOL — sobe backend (FastAPI :8000) e frontend (Vite :5173) em duas janelas do PowerShell.
# Uso, a partir da raiz do projeto:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
  Write-Host 'Ambiente Python não encontrado. Rode primeiro: py -3 -m venv backend\.venv; backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt'
  exit 1
}
if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
  Write-Host 'Dependências do frontend não encontradas. Rode primeiro: npm --prefix frontend install'
  exit 1
}
Start-Process powershell -WorkingDirectory $root -ArgumentList '-NoExit', '-Command', "& '$py' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"
Start-Process powershell -WorkingDirectory (Join-Path $root 'frontend') -ArgumentList '-NoExit', '-Command', 'npm run dev'
Write-Host 'Backend: http://127.0.0.1:8000/api/health   Frontend: http://localhost:5173'
