param(
    [string]$Label = "",
    [string]$ProjectId = "datosbotcursala",
    [string]$ServiceName = "cursala-bot",
    [string]$Region = "southamerica-east1"
)

$ErrorActionPreference = "Stop"

$backupScript = Join-Path $PSScriptRoot "create_backup.ps1"
if (-not (Test-Path $backupScript)) {
    throw "No se encontro create_backup.ps1 en $PSScriptRoot"
}

$resolvedLabel = $Label
if ([string]::IsNullOrWhiteSpace($resolvedLabel)) {
    $resolvedLabel = "pre-deploy"
}

Write-Host "[1/2] Creando backup antes de deploy..." -ForegroundColor Cyan
& $backupScript -Label $resolvedLabel -ProjectId $ProjectId -ServiceName $ServiceName -Region $Region
if ($LASTEXITCODE -ne 0) {
    throw "Fallo create_backup.ps1"
}

Write-Host "[2/2] Deploy a Cloud Run..." -ForegroundColor Cyan
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

gcloud run deploy $ServiceName --source . --region $Region --project $ProjectId --no-cpu-throttling --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Fallo deploy en Cloud Run"
}

Write-Host "Deploy finalizado con backup previo garantizado." -ForegroundColor Green
