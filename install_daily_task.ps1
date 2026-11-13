$ErrorActionPreference = 'Stop'

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectDir '.venv\Scripts\python.exe'
$runnerPath = Join-Path $projectDir 'run_pipeline.py'
$taskName = 'Utah County Showtimes Pipeline'
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Project Python environment not found at $pythonPath. Install requirements first."
}
if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Pipeline runner not found at $runnerPath."
}

$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "`"$runnerPath`" --trigger scheduled" `
    -WorkingDirectory $projectDir
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At '9:00 AM'
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($dailyTrigger, $logonTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description 'Collect Utah County showtime changes at 9 a.m. or at sign-in if no scheduled success has occurred that day.' `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
[PSCustomObject]@{
    TaskName = $task.TaskName
    State = $task.State
    DailyRunAt = '9:00 AM local time'
    CatchUpAtSignIn = $true
    StartWhenAvailable = $task.Settings.StartWhenAvailable
    NextRunTime = $info.NextRunTime
} | Format-List
