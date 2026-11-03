param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [Parameter(Mandatory = $true)][string]$IconPath,
    [Parameter(Mandatory = $true)][string]$ShortcutPath,
    [Parameter(Mandatory = $true)][string]$WorkDir
)

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($ShortcutPath)
$sc.TargetPath = $ExePath
$sc.WorkingDirectory = $WorkDir
$sc.IconLocation = "$IconPath,0"
$sc.Description = "PDF Print Checker"
$sc.Save()
Write-Host "Shortcut created: $ShortcutPath"
