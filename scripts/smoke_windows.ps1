param([string]$DistRoot = "dist\FET-Analyzer-v2")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Root = if ([IO.Path]::IsPathRooted($DistRoot)) { [IO.Path]::GetFullPath($DistRoot) } else { [IO.Path]::GetFullPath((Join-Path $ProjectRoot $DistRoot)) }
$Native = Join-Path $Root "FET-Analyzer-v2.exe"
$Browser = Join-Path $Root "FET-Analyzer-Browser.exe"
$Worker = Join-Path $Root "FET-Analyzer-Worker.exe"
foreach ($Executable in @($Native, $Browser, $Worker)) {
    if (-not (Test-Path -LiteralPath $Executable)) { throw "Missing executable: $Executable" }
    & $Executable --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "--help failed: $Executable" }
}

$SmokeParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$SmokeRoot = [IO.Path]::GetFullPath((Join-Path $SmokeParent ("fet-analyzer-smoke-" + [guid]::NewGuid().ToString("N"))))
if (-not $SmokeRoot.StartsWith($SmokeParent + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe smoke directory" }
New-Item -ItemType Directory -Path $SmokeRoot | Out-Null
$Csv = Join-Path $SmokeRoot "IdVg__Smoke_Detail_FET_Device__1.csv"
$Config = Join-Path $SmokeRoot "fet_analyzer_config.yaml"
Set-Content -LiteralPath $Csv -Encoding UTF8 -Value @(
    "Vg,Vd,Id,Ig",
    "-2,0.1,1e-8,1e-12",
    "-1,0.1,1e-7,1e-12",
    "0,0.1,1e-6,1e-12",
    "1,0.1,2e-6,1e-12",
    "2,0.1,3e-6,1e-12"
)
Set-Content -LiteralPath $Config -Encoding UTF8 -Value @(
    "device_defaults:",
    "  polarity: n",
    "  channel_length_um: 10.0",
    "transfer:",
    "  ion_method: fixed_vg",
    "  ion_fixed_vg_v: 2.0"
)
try {
    & $Worker --doctor --input $SmokeRoot --output (Join-Path $SmokeRoot "output") --config $Config
    if ($LASTEXITCODE -ne 0) { throw "Worker diagnostics failed" }
    & $Worker --input $SmokeRoot --output (Join-Path $SmokeRoot "output") --config $Config --dry-run
    if ($LASTEXITCODE -ne 0) { throw "Worker dry-run failed" }

    $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $Listener.Start()
    $Port = $Listener.LocalEndpoint.Port
    $Listener.Stop()
    $Process = Start-Process -FilePath $Browser -ArgumentList @("--root", ('"' + $SmokeRoot + '"'), "--port", $Port, "--no-browser") -PassThru -WindowStyle Hidden
    try {
        $Ready = $false
        for ($Attempt = 0; $Attempt -lt 40; $Attempt++) {
            try {
                $Response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/" -TimeoutSec 2
                if ($Response.StatusCode -eq 200 -and $Response.Content -match "FET Analysis Studio") { $Ready = $true; break }
            } catch { Start-Sleep -Milliseconds 250 }
        }
        if (-not $Ready) { throw "Browser dashboard did not serve HTTP 200" }
        $Body = @{config=$Config; overwrite=$true; workers=1; device_excel=$false; plot_copies=$false; batch_plots=$false} | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/run" -ContentType "application/json" -Body $Body | Out-Null
        $Finished = $false
        for ($Attempt = 0; $Attempt -lt 240; $Attempt++) {
            $Status = Invoke-RestMethod "http://127.0.0.1:$Port/api/status"
            if (-not $Status.running -and $null -ne $Status.return_code) {
                if ($Status.log -join "`n" -match "unrecognized arguments: -m fet_analyzer") { throw "Frozen worker recursion regression" }
                if ($Status.return_code -ne 0) { throw "Dashboard worker failed with exit code $($Status.return_code): $($Status.log -join '; ')" }
                foreach ($Relative in @("index.html", "run_manifest.json", "errors\error_report.json")) {
                    if (-not (Test-Path -LiteralPath (Join-Path $SmokeRoot "output\$Relative"))) { throw "Missing smoke output: $Relative" }
                }
                $Finished = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not $Finished) { throw "Dashboard-triggered analysis did not finish" }
    } finally {
        if ($Process -and -not $Process.HasExited) { Stop-Process -Id $Process.Id -Force }
    }
} finally {
    if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
}
Write-Host "Frozen Windows smoke tests passed."
