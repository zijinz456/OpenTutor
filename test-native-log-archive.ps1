#Requires -Version 5.1
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '..\scripts\native-log-archive.ps1')
$testRoot=Join-Path ([IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))) ('source-release\log-retention-tests\'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$utf8=New-Object Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $testRoot 'api.log'),"first api`r`nline two",$utf8)
[IO.File]::WriteAllText((Join-Path $testRoot 'api-error.log'),'original error',$utf8)
[IO.File]::WriteAllText((Join-Path $testRoot 'web.log'),'web stays live',$utf8)
$before=[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $testRoot 'api.log')))
$first=Move-NativePreviousLogs -Directory $testRoot -Service api
if(-not $first){throw 'No archive created'}
if(Test-Path -LiteralPath (Join-Path $testRoot 'api.log')){throw 'Old API log still in active path'}
if($before -ne [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $first 'api.log')))){throw 'Archive changed bytes'}
if([IO.File]::ReadAllText((Join-Path $testRoot 'web.log')) -ne 'web stays live'){throw 'Web log was touched'}
[IO.File]::WriteAllText((Join-Path $testRoot 'api.log'),'second api',$utf8)
$second=Move-NativePreviousLogs -Directory $testRoot -Service api
if($first -eq $second){throw 'Archive path reused'}
if([IO.File]::ReadAllText((Join-Path $second 'api.log')) -ne 'second api'){throw 'Second log lost'}
if([IO.File]::ReadAllText((Join-Path $first 'api-error.log')) -ne 'original error'){throw 'First error overwritten'}
if(Move-NativePreviousLogs -Directory $testRoot -Service api){throw 'Empty run created archive'}
Write-Output 'PASS: original bytes, separate services, repeated starts and missing logs'
