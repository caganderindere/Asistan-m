# Creates "Cuba" on the desktop, pointing at start.cmd.
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Cuba.lnk'))
$link.TargetPath = Join-Path $root 'start.cmd'
$link.WorkingDirectory = $root
$link.Description = 'Cuba - kisisel AI komuta merkezi'
$link.IconLocation = "$env:SystemRoot\System32\imageres.dll,-5373"
$link.WindowStyle = 7  # minimized: the console only hosts the server
$link.Save()
Write-Output "Shortcut: $(Join-Path $desktop 'Cuba.lnk')"
