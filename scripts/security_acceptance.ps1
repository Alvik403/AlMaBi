param(
    [string]$ProductionHost = "almabi.internal.example",
    [string]$SessionSecret = "acceptance-only-secret-with-at-least-32-characters"
)

$ErrorActionPreference = "Stop"
$env:SESSION_SECRET = $SessionSecret
$env:ALMABI_HOST = $ProductionHost

python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

python -m pip_audit -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw "pip-audit failed" }

npm audit --audit-level=high
if ($LASTEXITCODE -ne 0) { throw "npm audit failed" }

npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }

npm run test:browser
if ($LASTEXITCODE -ne 0) { throw "browser regression failed" }

docker compose -f docker-compose.prod.yml config --quiet
if ($LASTEXITCODE -ne 0) { throw "production compose validation failed" }

Write-Host "Security acceptance completed successfully."
