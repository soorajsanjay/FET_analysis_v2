param(
    [string[]]$FilePath = @(
        "dist\FET-Analyzer-v2\FET-Analyzer-v2.exe",
        "dist\FET-Analyzer-v2\FET-Analyzer-Browser.exe",
        "dist\FET-Analyzer-v2\FET-Analyzer-Worker.exe"
    ),
    [Parameter(Mandatory = $true)][string]$CertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Certificate = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object {
    $_.Thumbprint -eq $CertificateThumbprint.Replace(" ", "").ToUpperInvariant()
} | Select-Object -First 1
if (-not $Certificate) { throw "Certificate not found in Cert:\CurrentUser\My" }
if (-not $Certificate.HasPrivateKey) { throw "The selected certificate has no accessible private key" }

foreach ($RelativePath in $FilePath) {
    $Target = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $RelativePath))
    if (-not (Test-Path -LiteralPath $Target)) { throw "Executable not found: $Target" }
    $Signature = Set-AuthenticodeSignature -FilePath $Target -Certificate $Certificate `
        -HashAlgorithm SHA256 -TimestampServer $TimestampUrl
    if ($Signature.Status -ne "Valid") {
        throw "Signing failed for ${Target}: $($Signature.Status) - $($Signature.StatusMessage)"
    }
    Write-Host "Signed $Target with certificate $($Certificate.Thumbprint)"
}
