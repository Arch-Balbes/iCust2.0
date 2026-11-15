# Creates .env from .env.example with random passwords. Never overwrites an existing .env.
# ASCII only: Windows PowerShell 5.1 reads BOM-less UTF-8 scripts as ANSI.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) { Write-Host ".env already exists - left untouched"; exit 0 }

function New-Secret([int]$bytes = 24) {
    $b = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return ([Convert]::ToBase64String($b) -replace '[+/=]', 'x')
}

$content = Get-Content (Join-Path $root ".env.example") -Encoding UTF8
$content = $content -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$(New-Secret)"
$content = $content -replace '^MINIO_SECRET_KEY=.*', "MINIO_SECRET_KEY=$(New-Secret)"
[System.IO.File]::WriteAllLines($envFile, $content, (New-Object System.Text.UTF8Encoding $false))
Write-Host ".env created"
