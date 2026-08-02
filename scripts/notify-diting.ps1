<#
.SYNOPSIS
    谛听 · Windows 通知桥梁 — 通过 WSL 调用飞书通知脚本

.DESCRIPTION
    无凭据封装器，通过 WSL Ubuntu-24.04 调用
    /home/pitto/workspace/diting/scripts/notify-diting.sh
    并传递标题与正文。使用 -DryRun 可仅打印调用命令而不实际发送。

.PARAMETER Title
    通知标题，必填。

.PARAMETER Body
    通知正文，可选（留空则无正文内容）。

.PARAMETER DryRun
    仅打印将要执行的命令，不实际调用 WSL 脚本。

.EXAMPLE
    .\scripts\notify-diting.ps1 -Title "Task 00" -Body "dry run" -DryRun

.EXAMPLE
    .\scripts\notify-diting.ps1 -Title "部署成功" -Body "v0.8.0 已上线"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $false)]
    [string]$Body = "",

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# --- WSL availability check ------------------------------------------------
$wslDistro = "Ubuntu-24.04"
try {
    $wslList = & wsl --list --verbose 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "WSL is not available on this system. Exit code: $LASTEXITCODE"
        exit 1
    }
    # wsl --list --verbose may emit UTF-16LE with NUL bytes — sanitize
    $wslClean = ($wslList -replace "\x00", "") -join "`n"
    if ($wslClean -notmatch [regex]::Escape($wslDistro)) {
        Write-Error "WSL distribution '$wslDistro' not found. Available distributions:`n$wslClean"
        exit 1
    }
} catch {
    Write-Error "Failed to query WSL: $_"
    exit 1
}

# --- Resolve target script path inside WSL ---------------------------------
$wslScriptPath = "/home/pitto/workspace/diting/scripts/notify-diting.sh"

try {
    $scriptCheck = & wsl -d $wslDistro bash -c "test -f '$wslScriptPath' && echo 'OK' || echo 'MISSING'" 2>&1
    if ($scriptCheck -notmatch "OK") {
        Write-Error "Target script not found in WSL: $wslScriptPath"
        exit 1
    }
} catch {
    Write-Error "Failed to check target script in WSL: $_"
    exit 1
}

# --- Dry-run mode ----------------------------------------------------------
if ($DryRun) {
    Write-Host "[DRY RUN] Would execute:"
    Write-Host "  wsl -d $wslDistro bash '$wslScriptPath' '$Title' '$Body'"
    exit 0
}

# --- Execute notification --------------------------------------------------
try {
    $result = & wsl -d $wslDistro bash "$wslScriptPath" "$Title" "$Body" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Notification script failed (exit $LASTEXITCODE): $result"
        exit 1
    }
    Write-Host $result
} catch {
    Write-Error "Notification invocation failed: $_"
    exit 1
}
