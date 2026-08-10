<#
    Fjern SU Media AI Office planlagte opgaver igen fra Windows Opgavestyring.
    Sikker at koere: opgaver der ikke findes, springes bare over.
#>
$ErrorActionPreference = "Stop"

$names = @(
    "SU Media AI Office - Salgstjek",
    "SU Media AI Office - Dagligt refresh",
    "SU Media AI Office - Backup"
)

foreach ($name in $names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "Fjernet: $name"
    } else {
        Write-Host "Fandtes ikke: $name"
    }
}
