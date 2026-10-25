# Preserve the preceding service run before Start-Process opens its log files.
function Move-NativePreviousLogs {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory=$true)][string]$Directory,
        [Parameter(Mandatory=$true)][ValidateSet('api','web')][string]$Service
    )
    $logRoot=[IO.Path]::GetFullPath($Directory)
    $separator=[IO.Path]::DirectorySeparatorChar
    $prefix=$logRoot.TrimEnd($separator)+$separator
    $previous=@()
    foreach($name in @(($Service+'.log'),($Service+'-error.log'))) {
        $source=[IO.Path]::GetFullPath((Join-Path $logRoot $name))
        if(-not $source.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw '日志路径超出预期目录。'}
        if(Test-Path -LiteralPath $source -PathType Leaf){$previous+=$source}
    }
    if($previous.Count -eq 0){return $null}
    $session=[datetime]::UtcNow.ToString('yyyyMMdd-HHmmss-fff')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
    $archive=[IO.Path]::GetFullPath((Join-Path (Join-Path $logRoot 'archive') ($session+'-'+$Service)))
    if(-not $archive.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw '归档路径超出日志目录。'}
    [IO.Directory]::CreateDirectory($archive) | Out-Null
    foreach($source in $previous) {
        $destination=[IO.Path]::GetFullPath((Join-Path $archive ([IO.Path]::GetFileName($source))))
        if(-not $destination.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw '日志移动目标超出预期目录。'}
        Move-Item -LiteralPath $source -Destination $destination -ErrorAction Stop
    }
    return $archive
}
