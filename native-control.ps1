#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Start','Stop','Status','Backup','Clean')][string]$Action = 'Start',
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$nativeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$nativeData = Join-Path $nativeRoot 'native-data'
$nativeStatePath = Join-Path $nativeData 'runtime.json'
$nativePython = Join-Path $nativeRoot 'apps\api\.venv-win\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $nativePython)) { $nativePython = Join-Path $nativeRoot '.runtime\python\python.exe' }
$nativeNode = Join-Path $nativeRoot '.runtime\node\node.exe'
$nativeApiRunner = Join-Path $PSScriptRoot 'native-server.py'
$nativeWebRunner = Join-Path $PSScriptRoot 'native-web-server.cjs'
$nativeWebCli = Join-Path $nativeRoot 'apps\web\node_modules\next\dist\bin\next'
$nativeStandalone = Join-Path $nativeRoot 'apps\web\.next\standalone\apps\web\server.js'
if (Test-Path -LiteralPath $nativeStandalone) { $nativeWebCli = $nativeStandalone }
$nativeLogDir = Join-Path $nativeData 'logs'
. (Join-Path $PSScriptRoot 'native-log-archive.ps1')

function Get-NativeProcess($entry) {
    if (-not $entry) { return $null }
    $nativeCandidate = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
    if (-not $nativeCandidate) { return $null }
    if ($nativeCandidate.Path -ne $entry.executable) { return $null }
    if ([Math]::Abs(($nativeCandidate.StartTime.ToUniversalTime() - ([datetime]$entry.started_at).ToUniversalTime()).TotalSeconds) -gt 2) { return $null }
    return $nativeCandidate
}
function Read-NativeState {
    if (Test-Path -LiteralPath $nativeStatePath) { return Get-Content -LiteralPath $nativeStatePath -Raw | ConvertFrom-Json }
    return $null
}
function Save-NativeState($apiEntry,$webEntry) {
    $nativeTempState = $nativeStatePath + '.tmp'
    @{ api=$apiEntry; web=$webEntry; api_port=8000; web_port=3001; updated_at=[datetime]::UtcNow.ToString('o') } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $nativeTempState -Encoding UTF8
    Move-Item -LiteralPath $nativeTempState -Destination $nativeStatePath -Force
}
function Get-NativeEntry($process,[string]$executable) {
    # Start-Process may return before Windows exposes Process.Path. Record the
    # exact executable we launched; verify it against the live process on reuse.
    return @{pid=$process.Id; executable=[IO.Path]::GetFullPath($executable); started_at=$process.StartTime.ToUniversalTime().ToString('o')}
}
function Test-NativePort([int]$port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).Count -gt 0
}
function Wait-NativeUrl([string]$url,[int]$seconds) {
    $nativeDeadline=[datetime]::UtcNow.AddSeconds($seconds)
    while ([datetime]::UtcNow -lt $nativeDeadline) {
        try { $nativeResponse=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3; if ($nativeResponse.StatusCode -eq 200) { return } } catch { }
        Start-Sleep -Seconds 1
    }
    throw "服务启动超时。请查看 $nativeLogDir 中的日志。"
}

$nativeGateHash=[Security.Cryptography.SHA256]::Create()
$nativeGateName=([BitConverter]::ToString($nativeGateHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($nativeRoot.ToLowerInvariant())))).Replace('-','').Substring(0,16)
$nativeGateHash.Dispose()
$nativeGate=[Threading.Mutex]::new($false,('Local\OpenTutorNative_'+$nativeGateName))
$nativeLocked=$false
try {
    if ($Action -ne 'Status') {
        try { $nativeLocked=$nativeGate.WaitOne(0) } catch [Threading.AbandonedMutexException] { $nativeLocked=$true }
        if (-not $nativeLocked) { throw '已有启动、停止或备份操作正在进行，请稍候重试。' }
    }
$nativeState = Read-NativeState
if ($Action -eq 'Status') {
    $nativeApiProcess=Get-NativeProcess $nativeState.api
    $nativeWebProcess=Get-NativeProcess $nativeState.web
    [pscustomobject]@{ API=[bool]$nativeApiProcess; Web=[bool]$nativeWebProcess; URL='http://localhost:3001'; Data=$nativeData } | ConvertTo-Json
    exit 0
}
if ($Action -eq 'Stop') {
    foreach ($nativeEntry in @($nativeState.web,$nativeState.api)) {
        $nativeOwnedProcess=Get-NativeProcess $nativeEntry
        if ($nativeOwnedProcess) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $nativeOwnedProcess.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw '原生进程停止失败，请检查进程状态。' }
        }
    }
    if (Test-Path -LiteralPath $nativeStatePath) { Save-NativeState $null $null }
    Write-Output 'OpenTutor 原生服务已停止，学习资料保留。'
    exit 0
}
if ($Action -eq 'Clean') {
    & $nativePython -I -X utf8 (Join-Path $PSScriptRoot 'native-cleanup.py') --apply
    if ($LASTEXITCODE -ne 0) { throw '部分缓存未能清理，请关闭其他构建或测试程序后重试。核心代码与学习数据保留。' }
    exit 0
}
if ($Action -eq 'Backup') {
    & $nativePython -I -X utf8 (Join-Path $PSScriptRoot 'native-backup.py')
    if ($LASTEXITCODE -ne 0) { throw '本地备份未完成。' }
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $nativeData 'settings.env')) -and (Test-Path -LiteralPath $nativePython)) {
    & $nativePython -I -X utf8 (Join-Path $PSScriptRoot 'native-init.py')
    if ($LASTEXITCODE -ne 0) { throw '无法初始化本地配置，请确认安装目录可写。' }
}
foreach ($nativeRequired in @($nativePython,$nativeNode,$nativeWebCli,$nativeApiRunner,$nativeWebRunner,(Join-Path $nativeData 'settings.env'))) {
    if (-not (Test-Path -LiteralPath $nativeRequired)) { throw "运行文件缺失：$nativeRequired" }
}
[IO.Directory]::CreateDirectory($nativeLogDir) | Out-Null
$nativeApiProcess=Get-NativeProcess $nativeState.api
$nativeWebProcess=Get-NativeProcess $nativeState.web
if (-not $nativeApiProcess -and (Test-NativePort 8000)) { throw '端口 8000 正被其他服务使用；请先停止旧 Docker 版或其他服务。' }
if (-not $nativeWebProcess -and (Test-NativePort 3001)) { throw '端口 3001 正被其他服务使用；请先停止旧 Docker 版或其他服务。' }
try {
    if (-not $nativeApiProcess) {
        Move-NativePreviousLogs -Directory $nativeLogDir -Service api | Out-Null
        $nativeApiArgument='-I -X utf8 "' + $nativeApiRunner + '"'
        $nativeApiProcess=Start-Process -FilePath $nativePython -ArgumentList $nativeApiArgument -WorkingDirectory (Join-Path $nativeRoot 'apps\api') -WindowStyle Hidden -PassThru
    }
    Save-NativeState (Get-NativeEntry $nativeApiProcess $nativePython) $(if($nativeWebProcess){Get-NativeEntry $nativeWebProcess $nativeNode}else{$null})
    Wait-NativeUrl 'http://127.0.0.1:8000/api/health/live' 60
    if (-not $nativeWebProcess) {
        Move-NativePreviousLogs -Directory $nativeLogDir -Service web | Out-Null
        $nativeWebArguments=@("`"$nativeWebRunner`"")
        $nativeWebProcess=Start-Process -FilePath $nativeNode -ArgumentList $nativeWebArguments -WorkingDirectory (Join-Path $nativeRoot 'apps\web') -WindowStyle Hidden -PassThru
    }
    Save-NativeState (Get-NativeEntry $nativeApiProcess $nativePython) (Get-NativeEntry $nativeWebProcess $nativeNode)
    Wait-NativeUrl 'http://127.0.0.1:3001' 90
    Write-Output 'OpenTutor 已通过 Windows 原生方式启动：http://localhost:3001'
    if (-not $NoBrowser) { Start-Process 'http://localhost:3001' }
} catch {
    Write-Error $_
    exit 1
}

} finally {
    if ($nativeLocked) { $nativeGate.ReleaseMutex() }
    $nativeGate.Dispose()
}
