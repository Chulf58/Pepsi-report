<#
.SYNOPSIS
  Shows the "Pepsi prices updated" Windows notification; clicking it opens out\report.html.

.DESCRIPTION
  Call: notify.ps1 [-Status] <text> [-Title <text>] [-ReportPath <path>]. The status text
  (for example "OK, 8 offers") is the second line of the notification; -Message is an alias
  for -Status.

  Uses only built-in Windows PowerShell 5.1 APIs (Windows.UI.Notifications toast under the
  PowerShell app id). If the toast fails, falls back to a balloon tip and then to msg.exe,
  and says which one was used. Messages go to the console and to out\last-run.log.
#>
param(
    [Parameter(Position = 0)]
    [Alias('Message')]
    [string]$Status = 'Done',
    [string]$Title = 'Pepsi prices updated',
    [string]$ReportPath = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ReportPath) { $ReportPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'out\report.html' }
$logPath = Join-Path (Split-Path -Parent $ReportPath) 'last-run.log'

function Write-Log([string]$text) {
    Write-Output $text
    try { Add-Content -LiteralPath $logPath -Value $text -Encoding UTF8 }
    catch { [Console]::Error.WriteLine("notify.ps1: warning: cannot write $logPath ($($_.Exception.Message))") }
}

function Show-Toast {
    # The PowerShell app id is registered on every Windows install, so no shortcut or module is needed.
    $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    [void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
    $launch = ''
    if (Test-Path -LiteralPath $ReportPath) {
        $uri = [System.Security.SecurityElement]::Escape(([Uri](Resolve-Path -LiteralPath $ReportPath).ProviderPath).AbsoluteUri)
        $launch = " activationType=`"protocol`" launch=`"$uri`""
    }
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml(('<toast{0}><visual><binding template="ToastGeneric"><text>{1}</text><text>{2}</text></binding></visual></toast>' -f
            $launch, [System.Security.SecurityElement]::Escape($Title), [System.Security.SecurityElement]::Escape($Status)))
    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
}

function Show-Balloon {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Visible = $true
    $opens = Test-Path -LiteralPath $ReportPath
    if ($opens) {
        Register-ObjectEvent -InputObject $icon -EventName BalloonTipClicked -Action { Start-Process $event.MessageData } -MessageData $ReportPath | Out-Null
    }
    $icon.ShowBalloonTip(15000, $Title, $Status, [System.Windows.Forms.ToolTipIcon]::Info)
    Start-Sleep -Seconds 16
    $icon.Dispose()
}

try {
    Show-Toast
    Write-Log "notify.ps1: toast shown: $Title - $Status"
    exit 0
} catch {
    Write-Log "notify.ps1: toast failed ($($_.Exception.Message)); falling back to a balloon tip"
}

try {
    Show-Balloon
    Write-Log "notify.ps1: balloon tip shown (fallback)"
    exit 0
} catch {
    Write-Log "notify.ps1: balloon tip failed ($($_.Exception.Message)); falling back to msg.exe"
}

try {
    & msg.exe $env:USERNAME /TIME:60 "$Title - $Status"
    if ($LASTEXITCODE -ne 0) { throw "msg.exe exited with code $LASTEXITCODE" }
    Write-Log "notify.ps1: msg.exe message sent (fallback)"
    exit 0
} catch {
    Write-Log "notify.ps1: msg.exe failed ($($_.Exception.Message)); no notification was shown"
    exit 1
}
