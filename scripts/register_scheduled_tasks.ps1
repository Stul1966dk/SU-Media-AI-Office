<#
    Registrer SU Media AI Office planlagte opgaver i Windows Opgavestyring.

    - Koerer under den aktuelle bruger, kun naar du er logget paa.
    - Kraever IKKE administrator.
    - Er idempotent: kald igen for at opdatere. Eksisterende opgaver med samme
      navn fjernes foerst.

    Opgaver:
      1. Salgstjek        - hvert 30. minut (Partner Ads + Telegram)
      2. Dagligt refresh  - dagligt kl. 03:00 (data + eksperiment-monitorering)
      3. Backup           - dagligt kl. 03:30 (lokal databasebackup)

    Fjern igen med scripts\unregister_scheduled_tasks.ps1
#>
param(
    [string]$RefreshTime = "03:00",
    [string]$BackupTime  = "03:30",
    [int]$SalesIntervalMinutes = 30
)

$ErrorActionPreference = "Stop"

$ScriptsDir  = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptsDir

# Foretraek pythonw.exe (intet konsolvindue), ellers python.exe.
$pyCmd = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pyCmd) { throw "python blev ikke fundet i PATH." }
$pyDir   = Split-Path -Parent $pyCmd
$pythonw = Join-Path $pyDir "pythonw.exe"
$exe     = if (Test-Path $pythonw) { $pythonw } else { $pyCmd }

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

function Register-One {
    param([string]$Name, [string]$Script, $Trigger, [string]$Description)
    $target = Join-Path $ScriptsDir $Script
    $action = New-ScheduledTaskAction -Execute $exe `
        -Argument "`"$target`"" -WorkingDirectory $ProjectRoot
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger `
        -Settings $settings -Principal $principal -Description $Description | Out-Null
    Write-Host "Oprettet: $Name"
}

# Salgstjek: hvert N. minut, i praksis uden ophoer.
$salesTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $SalesIntervalMinutes) `
    -RepetitionDuration ([System.TimeSpan]::FromDays(3650))

$refreshTrigger = New-ScheduledTaskTrigger -Daily -At $RefreshTime
$backupTrigger  = New-ScheduledTaskTrigger -Daily -At $BackupTime

Register-One -Name "SU Media AI Office - Salgstjek" -Script "monitor_sales.py" `
    -Trigger $salesTrigger `
    -Description "Partner Ads salgstjek og Telegram-notifikation hver $SalesIntervalMinutes. minut."
Register-One -Name "SU Media AI Office - Dagligt refresh" -Script "daily_refresh.py" `
    -Trigger $refreshTrigger `
    -Description "Dagligt data-refresh og SEO-eksperiment-monitorering kl. $RefreshTime."
Register-One -Name "SU Media AI Office - Backup" -Script "backup_database.py" `
    -Trigger $backupTrigger `
    -Description "Daglig lokal databasebackup kl. $BackupTime."

Write-Host ""
Write-Host "Klar. Opgaverne ligger i Windows Opgavestyring i bibliotekets rod."
