$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path $PSScriptRoot -Parent
$demoPython = Join-Path $demoRoot '.hermes-venv\Scripts\python.exe'
$demoSession = Join-Path $env:USERPROFILE '.config\xiaozhi-sandbox-demo\secrets\hermes-control-session.json'
if (Test-Path -LiteralPath $demoSession) { throw 'An existing demo session may be running. Open it or stop it first.' }
$demoLog = Join-Path $demoRoot 'hermes-control.log'
$demoErr = Join-Path $demoRoot 'hermes-control.err.log'
$demoProcess = Start-Process -FilePath $demoPython -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'launch.py') + '"')) -WorkingDirectory $demoRoot -WindowStyle Hidden -RedirectStandardOutput $demoLog -RedirectStandardError $demoErr -PassThru
for ($demoAttempt = 0; $demoAttempt -lt 150; $demoAttempt++) {
    if (Test-Path -LiteralPath $demoSession) {
        $demoUrl = (Get-Content -Raw -LiteralPath $demoSession | ConvertFrom-Json).url
        Start-Process $demoUrl
        Write-Output '演示已打开；结束时点击页面中的“结束演示并释放沙箱”。'
        exit 0
    }
    if ($demoProcess.HasExited) { throw "启动失败，请查看 $demoErr" }
    Start-Sleep -Seconds 3
}
throw '启动仍未完成，请查看日志；不要重复启动。'
