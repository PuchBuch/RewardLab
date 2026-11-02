<#
  Запуск всех сервисов RewardLab без Docker (Windows).
    .\run_all.ps1          запустить (если уже запущены — перезапустить)
    .\run_all.ps1 -Stop    остановить
  Логи: microservices\logs\<сервис>.log
#>
param([switch]$Stop)

$root     = $PSScriptRoot
$services = "auth", "wallet", "games", "community", "gateway"   # gateway последним
$pidFile  = Join-Path $root "data\pids.txt"

function Stop-Services {
    if (Test-Path $pidFile) {
        foreach ($id in Get-Content $pidFile) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $pidFile
    }
}

Stop-Services
if ($Stop) { Write-Host "RewardLab stopped."; return }

$py = Join-Path $root "..\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

# .env с новыми случайными ключами, если его ещё нет
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    $secret = & $py -c "import secrets; print(secrets.token_hex(32))"
    $token  = & $py -c "import secrets; print(secrets.token_hex(32))"
    "APP_SECRET=$secret`nINTERNAL_TOKEN=$token`nCOOKIE_SECURE=0`nTRUST_PROXY=0" |
        Set-Content $envFile -Encoding ascii
    Write-Host "Created .env with new random keys."
}

New-Item -ItemType Directory -Force (Join-Path $root "logs"), (Join-Path $root "data") | Out-Null
$ids = foreach ($s in $services) {
    $log = Join-Path $root "logs\$s.log"
    $p = Start-Process $py -ArgumentList "-m", "$s.app" -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $root "logs\$s.err.log")
    $p.Id
}
$ids | Set-Content $pidFile

# Дождаться, пока gateway ответит
foreach ($i in 1..30) {
    try { Invoke-WebRequest "http://127.0.0.1:5000/health" -UseBasicParsing -TimeoutSec 1 | Out-Null; break }
    catch { Start-Sleep -Milliseconds 500 }
}
Write-Host "RewardLab is running: http://127.0.0.1:5000   (stop: .\run_all.ps1 -Stop)"
