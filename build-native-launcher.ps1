#Requires -Version 5.1
param([switch]$DesktopShortcut)
$ErrorActionPreference='Stop'
$launcherRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$launcherCsc=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if(-not(Test-Path -LiteralPath $launcherCsc)){throw '未找到 Windows .NET Framework 编译器。'}
Add-Type -AssemblyName System.Drawing
$launcherBitmap=[Drawing.Bitmap]::new(64,64)
$launcherGraphics=[Drawing.Graphics]::FromImage($launcherBitmap)
$launcherGraphics.Clear([Drawing.Color]::FromArgb(28,49,47))
$launcherBrush=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(197,221,204))
$launcherGraphics.FillRectangle($launcherBrush,12,15,18,35)
$launcherGraphics.FillRectangle($launcherBrush,34,15,18,35)
$launcherPen=[Drawing.Pen]::new([Drawing.Color]::FromArgb(28,49,47),2)
foreach($launcherLine in 24,32,40){$launcherGraphics.DrawLine($launcherPen,16,$launcherLine,26,$launcherLine);$launcherGraphics.DrawLine($launcherPen,38,$launcherLine,48,$launcherLine)}
$launcherIcon=[Drawing.Icon]::FromHandle($launcherBitmap.GetHicon())
$launcherIconPath=Join-Path $PSScriptRoot 'windows\OpenTutor.ico'
$launcherStream=[IO.File]::Create($launcherIconPath)
$launcherIcon.Save($launcherStream)
$launcherStream.Dispose();$launcherIcon.Dispose();$launcherPen.Dispose();$launcherBrush.Dispose();$launcherGraphics.Dispose();$launcherBitmap.Dispose()
& $launcherCsc /nologo /target:winexe /platform:x64 /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/win32icon:$launcherIconPath" "/out:$launcherRoot\OpenTutor.exe" (Join-Path $PSScriptRoot 'windows\Launcher.cs')
if($LASTEXITCODE -ne 0){throw 'EXE 构建失败。'}
Write-Output "EXE 启动器已生成：$launcherRoot\OpenTutor.exe"

if($DesktopShortcut) {
    $launcherDesktop=[Environment]::GetFolderPath('DesktopDirectory')
    $launcherShell=New-Object -ComObject WScript.Shell
    $launcherLinkPath=Join-Path $launcherDesktop 'OpenTutor 本地学习.lnk'
    $launcherLink=$launcherShell.CreateShortcut($launcherLinkPath)
    $launcherLink.TargetPath=Join-Path $launcherRoot 'OpenTutor.exe'
    $launcherLink.WorkingDirectory=$launcherRoot
    $launcherLink.IconLocation=(Join-Path $launcherRoot 'OpenTutor.exe')+',0'
    $launcherLink.Description='一键启动 OpenTutor，本地保存学习进度'
    $launcherLink.Save()
    Write-Output "桌面快捷方式已创建：$launcherLinkPath"
}
