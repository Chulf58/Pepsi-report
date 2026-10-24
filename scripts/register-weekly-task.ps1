<#
.SYNOPSIS
  Registers (or with -Unregister removes) the Task Scheduler task "PepsiReport weekly prices".

.DESCRIPTION
  Runs scripts/weekly-run.sh in WSL every Monday at 07:00 local time, as the current user,
  only while that user is logged on (the notification needs a session). StartWhenAvailable
  runs a missed start at the next login or wake. Safe to run again: it replaces the task.
  -WhatIf shows what would happen and changes nothing.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$taskName = 'PepsiReport weekly prices'
$distro = 'Ubuntu-24.04'
$wslScript = '/mnt/c/Users/chulf/PepsiReport/scripts/weekly-run.sh'
$arguments = "-d $distro -- bash $wslScript"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($Unregister) {
    if (-not $existing) {
        Write-Output "Task '$taskName' is not registered; nothing to remove."
        exit 0
    }
    if ($PSCmdlet.ShouldProcess($taskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "Task '$taskName' removed."
    }
    exit 0
}

$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '07:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

$verb = if ($existing) { 'Replace' } else { 'Register' }
if ($PSCmdlet.ShouldProcess($taskName, "$verb scheduled task: Mondays 07:00 as $user, wsl.exe $arguments")) {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description 'Runs the Pepsi Max / Cult Energy price finder, commits data/history.csv and shows a notification.' | Out-Null
    Write-Output "Task '$taskName' registered: Mondays 07:00 as $user, wsl.exe $arguments"
}
