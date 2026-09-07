param([string]$DistRoot = "dist\FET-Analyzer-v2")
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Root = if ([IO.Path]::IsPathRooted($DistRoot)) { [IO.Path]::GetFullPath($DistRoot) } else { [IO.Path]::GetFullPath((Join-Path $ProjectRoot $DistRoot)) }
& "$PSScriptRoot\smoke_windows.ps1" -DistRoot $Root
$Zip = Join-Path (Split-Path $Root -Parent) "FET-Analyzer-v2-windows-portable.zip"
Compress-Archive -LiteralPath $Root -DestinationPath $Zip -Force
$Hash = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$Hash  $([IO.Path]::GetFileName($Zip))" | Set-Content -LiteralPath "$Zip.sha256" -Encoding ASCII
Write-Host "Verified portable archive: $Zip"
Write-Host "SHA-256: $Hash"
