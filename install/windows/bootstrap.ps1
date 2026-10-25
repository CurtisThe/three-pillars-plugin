# bootstrap.ps1 - Stage 0 of the three-pillars Windows workstation setup.
# Run it in PowerShell opened with "Run as administrator". It is idempotent:
# safe to run again after a reboot or after fixing something it reported.
# It only checks and installs. It never changes Group Policy, never touches
# antivirus settings and never loosens a security setting. When the machine
# blocks a step it prints one "needs IT" line to send to your IT team and
# stops, so nothing is worked around.
#
# Exit codes:
#   0  done, or a reboot is pending and this script resumes after it
#   1  a step failed: run the script again, finished steps are skipped
#   2  not running as administrator
#   3  needs IT: something on this machine blocks WSL2
#   4  needs BIOS: CPU virtualization is turned off
#
# Pass -Resume when Windows runs the script again after a reboot (RunOnce); it
# then waits for Enter before closing so the result can be read.
#Requires -Version 5.1
param([switch]$Resume)

$ErrorActionPreference = 'Stop'

# Shared constants; the same literals are used by the other Stage 0 steps.
$Distro = 'Ubuntu-24.04'
$SelfDir = "$env:ProgramData\three-pillars"
$Self = "$SelfDir\bootstrap.ps1"
$RunOnceKey = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
$RunOnceName = 'ThreePillarsBootstrap'
$RawBase = 'https://raw.githubusercontent.com/CurtisThe/three-pillars-plugin/HEAD/install/windows/'
$Features = @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')

# The ordered steps; each one after preflight is Invoke-Step<Name> (kebab to Pascal case).
$Steps = @(
    'preflight', 'wsl-features', 'resume-entry', 'ubuntu',
    'claude-code', 'install-files', 'open-readme'
)
# Step name -> done | already | reboot | skipped, printed as SUMMARY lines.
$State = @{}

# The only place this script exits.
function Exit-Bootstrap([int]$Code) {
    if ($Resume) { Read-Host 'Press Enter to close' | Out-Null }
    exit $Code
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $role = [Security.Principal.WindowsBuiltInRole]::Administrator
    if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole($role)) {
        Write-Output 'run this in PowerShell opened with Run as administrator'
        Exit-Bootstrap 2
    }
}

# Every block that only IT can lift ends here, with one line to send on.
function Stop-NeedsIT([string]$Reason) {
    Write-Output "needs IT: $Reason"
    Write-Output 'Send the line above to your IT team and change nothing on this machine.'
    Exit-Bootstrap 3
}

# A step that is not blocked by IT but did not finish: say so and stop.
function Stop-Failed([string]$Reason) {
    Write-Output "step failed: $Reason"
    Write-Output 'Run this script again; steps that are already done are skipped.'
    Exit-Bootstrap 1
}

function Write-Summary {
    foreach ($step in $Steps) {
        $result = 'skipped'
        if ($State.ContainsKey($step)) { $result = $State[$step] }
        Write-Output "SUMMARY $step=$result"
    }
}

# Windows runs the saved copy as administrator after the reboot, so only
# Administrators and SYSTEM may write where it lives. Any local account can create
# a folder under ProgramData, so take the folder over and replace its permissions.
function Protect-SelfDir {
    New-Item -ItemType Directory -Force -Path $SelfDir | Out-Null
    foreach ($path in @($SelfDir, $Self)) {
        $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            Stop-Failed "$path is a link; delete it and run this again"
        }
    }
    & takeown.exe /F $SelfDir /A | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Failed "could not take ownership of $SelfDir" }
    & icacls.exe $SelfDir /reset /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Failed "could not reset the permissions of $SelfDir" }
    & icacls.exe $SelfDir /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Failed "could not lock the permissions of $SelfDir" }
    if (Test-Path -LiteralPath $Self -PathType Container) { Stop-Failed "$Self is a folder; delete it and run this again" }
    if (Test-Path -LiteralPath $Self) { [IO.File]::Delete($Self) }
}

function Invoke-Preflight {
    Test-Admin
    if ([Environment]::OSVersion.Version.Build -lt 19041) {
        Stop-NeedsIT 'Windows build is older than 19041 (WSL2 needs 2004 or later)'
    }
    $wsl = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WSL' -Name AllowWSL -ErrorAction SilentlyContinue
    if ($wsl -and $wsl.AllowWSL -eq 0) {
        Stop-NeedsIT 'WSL is turned off by policy'
    }
    $firmware = @(Get-CimInstance Win32_Processor | Where-Object { $_.VirtualizationFirmwareEnabled })
    $hypervisor = [bool](Get-CimInstance Win32_ComputerSystem).HypervisorPresent
    if ($firmware.Count -eq 0 -and -not $hypervisor) {
        Write-Output 'needs BIOS: turn on CPU virtualization (task step bios-virtualization), then run this again'
        Exit-Bootstrap 4
    }
    # RunOnce needs a file on disk to run after the reboot.
    if ($PSCommandPath -and ($PSCommandPath -ne $Self)) {
        Protect-SelfDir
        Copy-Item -Path $PSCommandPath -Destination $Self -Force
    }
}

# A policy or antivirus block on a feature is reported, never worked around.
function Invoke-StepWslFeatures {
    $changed = $false
    $restart = $false
    foreach ($name in $Features) {
        try {
            $current = (Get-WindowsOptionalFeature -Online -FeatureName $name).State
            if ($current -eq 'Enabled') { continue }
            $changed = $true
            if ($current -eq 'EnablePending') { $restart = $true; continue }
            $enabled = Enable-WindowsOptionalFeature -Online -FeatureName $name -All -NoRestart
            if ($enabled.RestartNeeded) { $restart = $true }
        } catch {
            Stop-NeedsIT "could not turn on ${name}: $($_.Exception.Message)"
        }
    }
    if ($restart) { $State['wsl-features'] = 'reboot' }
    elseif ($changed) { $State['wsl-features'] = 'done' }
    else { $State['wsl-features'] = 'already' }
}

# Everything after this step needs WSL, so a pending reboot ends this run here.
function Invoke-StepResumeEntry {
    if ($State['wsl-features'] -ne 'reboot') {
        $State['resume-entry'] = 'skipped'
        return
    }
    Set-ItemProperty -Path $RunOnceKey -Name $RunOnceName -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Self`" -Resume"
    $State['resume-entry'] = 'done'
    Write-Summary
    Write-Output 'Reboot now. Setup continues by itself after you sign in.'
    Exit-Bootstrap 0
}

function Invoke-StepUbuntu {
    $listed = (& wsl.exe -l -q) -join "`n"
    $names = ($listed -replace "`0", '') -split '\s+'
    if ($names -contains $Distro) {
        $State['ubuntu'] = 'already'
        return
    }
    Write-Output 'A window opens for Ubuntu. Create your Ubuntu user name and password there.'
    & wsl.exe --install -d $Distro
    if ($LASTEXITCODE -ne 0) { Stop-Failed "wsl.exe could not install $Distro" }
    Read-Host 'Press Enter here once your Ubuntu user is created' | Out-Null
    $State['ubuntu'] = 'done'
}

function Invoke-StepClaudeCode {
    & wsl.exe -d $Distro -- bash -lc 'command -v claude' | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $State['claude-code'] = 'already'
        return
    }
    & wsl.exe -d $Distro -- bash -lc 'curl -fsSL https://claude.ai/install.sh | bash'
    if ($LASTEXITCODE -ne 0) { Stop-Failed 'the Claude Code installer did not finish' }
    $State['claude-code'] = 'done'
}

# Public files only: no login, no token.
function Invoke-StepInstallFiles {
    $dir = '~/three-pillars-install/'
    & wsl.exe -d $Distro -- bash -lc "mkdir -p $dir"
    if ($LASTEXITCODE -ne 0) { Stop-Failed "could not create $dir in $Distro" }
    $fetched = $false
    foreach ($f in @('README.md', 'doctor.sh')) {
        & wsl.exe -d $Distro -- bash -lc "test -f $dir$f" | Out-Null
        if ($LASTEXITCODE -eq 0) { continue }
        $fetched = $true
        & wsl.exe -d $Distro -- bash -lc "curl -fsSL '$RawBase$f' -o $dir$f"
        if ($LASTEXITCODE -ne 0) { Stop-Failed "could not download $f" }
    }
    if ($fetched) { $State['install-files'] = 'done' }
    else { $State['install-files'] = 'already' }
}

# The bash string holds no double quote: PowerShell 5.1 mangles them in native arguments.
function Invoke-StepOpenReadme {
    $cmd = 'cd ~/three-pillars-install && claude ''Follow README.md in this folder.'''
    Start-Process -FilePath wsl.exe -ArgumentList "-d $Distro --cd ~ -- bash -lc `"$cmd`""
    $State['open-readme'] = 'done'
}

# Windows deletes a RunOnce value when it runs it; this clears a leftover.
Remove-ItemProperty -Path $RunOnceKey -Name $RunOnceName -ErrorAction SilentlyContinue
Invoke-Preflight
$State['preflight'] = 'done'
foreach ($step in $Steps) {
    if ($step -eq 'preflight') { continue }
    $words = $step -split '-' | ForEach-Object { $_.Substring(0, 1).ToUpperInvariant() + $_.Substring(1) }
    & ('Invoke-Step' + ($words -join ''))
}
Write-Summary
Exit-Bootstrap 0
