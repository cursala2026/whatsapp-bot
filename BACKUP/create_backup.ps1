param(
    [string]$Label = "",
    [string]$ServiceName = "datosbotcursala",
    [string]$Region = "southamerica-east1",
    [string]$WebhookUrl = ""
)

$ErrorActionPreference = "Stop"

# Script location is BACKUP; repository root is one level up.
$backupRoot = $PSScriptRoot
$repoRoot = Split-Path -Parent $backupRoot

Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$labelSlug = ""
if (-not [string]::IsNullOrWhiteSpace($Label)) {
    $labelSlug = "_" + ($Label -replace "[^a-zA-Z0-9_-]", "-")
}

$targetDir = Join-Path $backupRoot ("{0}{1}" -f $timestamp, $labelSlug)
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$filesToBackup = @(
    "main.py",
    "menu_config.json",
    "enviar.py",
    "requirements.txt",
    "README.md",
    ".gitignore"
)

foreach ($file in $filesToBackup) {
    if (Test-Path $file) {
        Copy-Item -Path $file -Destination (Join-Path $targetDir (Split-Path $file -Leaf)) -Force
    }
}

$branch = ""
$commit = ""
$status = ""

if (Get-Command git -ErrorAction SilentlyContinue) {
    $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
    $commit = (git rev-parse --short HEAD 2>$null)
    $status = ((git status --short --branch 2>$null) | Out-String).Trim()
}

$cloudRunUrl = ""
$cloudRunRevision = ""
if (Get-Command gcloud -ErrorAction SilentlyContinue) {
    try {
        $cloudRun = gcloud run services describe $ServiceName --region=$Region --format="value(status.url,status.latestReadyRevisionName)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $cloudRun) {
            $parts = $cloudRun -split "\s+"
            if ($parts.Length -ge 1) { $cloudRunUrl = $parts[0] }
            if ($parts.Length -ge 2) { $cloudRunRevision = $parts[1] }
        }
    }
    catch {
        # Keep backup process running even if gcloud cannot resolve service details.
    }
}

$resolvedWebhookUrl = ""
if (-not [string]::IsNullOrWhiteSpace($WebhookUrl)) {
    $resolvedWebhookUrl = $WebhookUrl
}
elseif (-not [string]::IsNullOrWhiteSpace($cloudRunUrl)) {
    $resolvedWebhookUrl = "$($cloudRunUrl.TrimEnd('/'))/webhook"
}

$metadata = @(
    "created_at=$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))",
    "label=$Label",
    "git_branch=$branch",
    "git_commit=$commit",
    "git_status=$status",
    "service_name=$ServiceName",
    "service_region=$Region",
    "webhook_url=$resolvedWebhookUrl",
    "cloud_run_url=$cloudRunUrl",
    "cloud_run_revision=$cloudRunRevision",
    "local_port=8080"
)
$metadata | Set-Content -Path (Join-Path $targetDir "metadata.txt") -Encoding UTF8

$restoreInstructions = @(
    "Restore quick steps",
    "1) Copy desired backup files from this folder to repository root.",
    "2) Validate with: git status --short --branch",
    "3) Redeploy if needed:",
    "   gcloud run deploy $ServiceName --source . --region $Region --allow-unauthenticated --quiet",
    "4) Verify webhook URL in Meta:",
    "   $resolvedWebhookUrl"
)
$restoreInstructions | Set-Content -Path (Join-Path $targetDir "restore_instructions.txt") -Encoding UTF8

Write-Host "Backup created in $targetDir"
