<#
.SYNOPSIS
	WorkerStatus.ps1 と StartWorker.ps1 の回帰テスト(#195)。本物の Orca は呼ばない。

.DESCRIPTION
	PATH の先頭に偽の orca.ps1 を置いて実行する。実行の前に Get-Command で偽物が解決されることを確かめ、
	そうでなければ失敗する。ORCA_CLI_COMMAND は消しておき、それを使うことを確かめるときだけ偽物の別名を指す。

.EXAMPLE
	pwsh -NoProfile -File Tests/WorkerTools.Tests.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$failures = [System.Collections.Generic.List[string]]::new()
function Check([bool]$condition, [string]$message) {
	if ($condition) { Write-Host "  ok: $message" }
	else {
		Write-Host "  NG: $message" -ForegroundColor Red
		$failures.Add($message)
	}
}

$fakeOrca = @'
# 偽の orca(テスト用)。worker-list は 2 ページに分けて答える
Add-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "orca.log") -Value "$args" -Encoding utf8
function Write-Worker($id, $state, $outcome, $terminalState) {
	[pscustomobject]@{ dispatchId = $id; taskId = "task_$id"; state = $state; outcome = $outcome; liveness = "unverifiable"; terminal = "structworker_$id"; terminalState = $terminalState; attention = @("unverifiable") }
}
if ($args[1] -eq "worker-list") {
	if ($env:LOOPBGM_TEST_ORCA_FAIL -eq "list") { Write-Output '{"ok":false}'; exit 1 }
	if ($args -contains "--cursor") {
		$result = [pscustomobject]@{ workers = @((Write-Worker "dead" "ready" "in_progress" "active"), (Write-Worker "unread" "ready" "in_progress" "active"), (Write-Worker "gone" "done" "succeeded" "released")) }
	}
	else {
		$finished = Write-Worker "finished" "done" "succeeded" "retained"
		$finished | Add-Member -NotePropertyName next -NotePropertyValue ([pscustomobject]@{ command = "worker-release --dispatch finished" })
		$result = [pscustomobject]@{ workers = @((Write-Worker "live" "ready" "in_progress" "active"), $finished); nextCursor = "page2" }
	}
	ConvertTo-Json -Depth 5 -InputObject ([pscustomobject]@{ ok = $true; result = $result })
	exit 0
}
if ($args[1] -eq "worker-read") {
	$id = $args[[array]::IndexOf($args, "--dispatch") + 1]
	if ($id -eq "unread") { exit 1 }
	$terminal = if ($id -in "dead", "finished") { "exited" } else { "running" }
	ConvertTo-Json -Depth 5 -InputObject ([pscustomobject]@{ ok = $true; result = [pscustomobject]@{ status = [pscustomobject]@{ worker = "ready"; terminal = $terminal; liveness = "live" } } })
	exit 0
}
if ($args[1] -eq "worker-start" -and $args -contains "--retry-of") {
	# 本物と同じく、再試行には --task が要り、仕様は渡せない
	if ($args -notcontains "--task" -or $args -contains "--spec-file") { Write-Output "--retry-of needs --task"; exit 3 }
	Write-Output "retried"
	exit 0
}
if ($args[1] -eq "worker-start") {
	$spec = $args[[array]::IndexOf($args, "--spec-file") + 1]
	Copy-Item -LiteralPath $spec -Destination (Join-Path $env:LOOPBGM_TEST_STATE "spec.md")
	Set-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "spec-path.txt") -Value $spec -Encoding utf8
	Write-Output "started"
	exit [int]$env:LOOPBGM_TEST_ORCA_START_EXIT
}
exit 1
'@

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("loopbgm_workertools_test_" + [guid]::NewGuid().ToString("N"))
$bin = Join-Path $root "bin"
$state = Join-Path $root "state"
$savedPath = $env:PATH
$savedCli = $env:ORCA_CLI_COMMAND
try {
	$env:ORCA_CLI_COMMAND = $null
	New-Item -ItemType Directory -Path $bin, $state | Out-Null
	Set-Content -LiteralPath (Join-Path $bin "orca.ps1") -Value $fakeOrca -Encoding utf8
	$env:PATH = "$bin;$savedPath"
	$env:LOOPBGM_TEST_STATE = $state
	$env:LOOPBGM_TEST_ORCA_START_EXIT = "0"
	if ((Get-Command orca).Source -notlike "$bin*") { throw "偽の orca が解決されません: $((Get-Command orca).Source)" }
	$log = Join-Path $state "orca.log"

	function Invoke-Tool([string]$Script, [string[]]$Arguments) {
		Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue
		$output = & pwsh -NoProfile -File (Join-Path $RepoRoot $Script) @Arguments 2>&1 | Out-String
		[pscustomobject]@{ Exit = $LASTEXITCODE; Output = $output; Log = $(if (Test-Path $log) { Get-Content -Raw -Encoding utf8 $log } else { "" }) }
	}

	Write-Host "== WorkerStatus.ps1 =="
	$r = Invoke-Tool "WorkerStatus.ps1" @("-Run", "run_x", "-Json")
	$rows = @($r.Output | ConvertFrom-Json)
	Check ($r.Exit -eq 0 -and $rows.Count -eq 5) "follows nextCursor and lists every worker (実際: $($rows.Count))"
	Check ($r.Log -match "worker-list --limit 100 --run run_x") "passes the Run"
	$byId = @{}
	foreach ($row in $rows) { $byId[$row.Dispatch] = $row }
	Check (-not $byId["live"].Exited -and -not $byId["live"].NeedsAttention) "a running worker is fine"
	Check ($byId["dead"].Exited -and $byId["dead"].NeedsAttention) "an exited worker in progress needs attention"
	Check ($byId["finished"].Exited -and -not $byId["finished"].NeedsAttention) "an exited worker that finished does not need attention"
	Check ($byId["unread"].Terminal -eq "unknown" -and $byId["unread"].NeedsAttention) "a worker that cannot be read is unknown, not fine"
	Check ($byId["gone"].Terminal -eq "released" -and $r.Log -notmatch "--dispatch gone") "a released worker is not read"

	$r = Invoke-Tool "WorkerStatus.ps1" @()
	Check ($r.Exit -eq 0 -and $r.Output -match "\*\*\* EXITED \*\*\*\s+dead") "the text output flags exited workers"
	Check ($r.Output -match "要確認: dead" -and $r.Output -notmatch "要確認: finished") "the text output names what needs attention"
	Check ($r.Output -match "next があればそれに従い" -and $r.Output -notmatch "起動し直して") "it points to next and the recovery guide, not to a restart (#7)"
	Check ($r.Output -match "finished .*next=\{""command"":""worker-release --dispatch finished""\}" -and $r.Output -match "attention=unverifiable") "the text output shows next and attention from worker-list"
	Check ($r.Output -match "ワーカー 5 件、exited 2 件、未完了で動いていると確かめられないもの 2 件") "the summary counts them"

	$env:LOOPBGM_TEST_ORCA_FAIL = "list"
	$r = Invoke-Tool "WorkerStatus.ps1" @()
	$env:LOOPBGM_TEST_ORCA_FAIL = ""
	Check ($r.Exit -eq 1 -and $r.Output -match "worker-list を読めませんでした") "a failed list is an error"

	Write-Host "== StartWorker.ps1 =="
	$specFile = Join-Path $state "input.md"
	Set-Content -LiteralPath $specFile -Value "## タスク: テストの仕様" -Encoding utf8
	$rulesFirstLine = "## Rules for every worker"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x")
	$sent = Get-Content -Raw -Encoding utf8 (Join-Path $state "spec.md")
	Check ($r.Exit -eq 0 -and $r.Output -match "started") "starts the worker"
	Check ($sent.StartsWith($rulesFirstLine) -and $sent -match "タスク: テストの仕様") "the spec is the common rules (without the last-reviewed line) followed by the task"
	Check ($sent.IndexOf("PrePr.ps1") -ge 0 -and $sent.IndexOf("CodexReview.ps1 -Pr <N> -Post") -ge 0) "the rules contain the new review flow"
	Check ($r.Log -match "--agent claude --worktree new-top-level --name issue-1-x --base-branch origin/develop --setup run" -and $r.Log -notmatch "--model") "normal: a new worktree from origin/develop, no model override"
	Check (-not (Test-Path -LiteralPath (Get-Content -Encoding utf8 (Join-Path $state "spec-path.txt")))) "the temporary spec is deleted"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x", "-Model", "some-model", "-Effort", "high", "-Run", "run_x")
	Check ($r.Exit -eq 0 -and $r.Log -match "--model some-model --effort high" -and $r.Log -match "--run run_x") "-Model and -Effort are passed only when given; the Run is passed"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x", "-Effort", "high")
	Check ($r.Exit -eq 2 -and -not $r.Log) "-Effort without -Model is refused before orca"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x", "-Size", "small")
	Check ($r.Exit -ne 0 -and -not $r.Log) "the fixed small model is gone (-Size is no longer accepted, #7)"

	# ORCA_CLI_COMMAND があればそれを使う(PATH の orca には何も書かない別の偽物を置く)
	$cliDir = Join-Path $root "cli"
	New-Item -ItemType Directory -Path $cliDir | Out-Null
	Set-Content -LiteralPath (Join-Path $cliDir "session-orca.ps1") -Value ($fakeOrca.Replace('"orca.log"', '"session-orca.log"')) -Encoding utf8
	$sessionLog = Join-Path $state "session-orca.log"
	$env:ORCA_CLI_COMMAND = Join-Path $cliDir "session-orca.ps1"
	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x")
	$s = Invoke-Tool "WorkerStatus.ps1" @("-Json")
	$sessionText = if (Test-Path $sessionLog) { Get-Content -Raw -Encoding utf8 $sessionLog } else { "" }
	Check ($r.Exit -eq 0 -and -not $r.Log -and $s.Exit -eq 0 -and -not $s.Log -and $sessionText -match "worker-start" -and $sessionText -match "worker-list") "ORCA_CLI_COMMAND is used instead of the orca on PATH"

	$env:ORCA_CLI_COMMAND = Join-Path $cliDir "missing-orca.exe"
	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x")
	Check ($r.Exit -eq 1 -and -not $r.Log -and $r.Output -match "missing-orca") "a broken ORCA_CLI_COMMAND fails instead of falling back to PATH"
	$env:ORCA_CLI_COMMAND = $null

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Worktree", "path:C:/w")
	Check ($r.Exit -eq 0 -and $r.Log -match "--worktree path:C:/w" -and $r.Log -notmatch "--name|--setup|--base-branch") "an existing worktree takes no creation flags"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "issue-1-x", "-BaseBranch", "origin/feature/x")
	Check ($r.Exit -eq 0 -and $r.Log -match "--base-branch origin/feature/x") "-BaseBranch overrides the base"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Worktree", "path:C:/w", "-BaseBranch", "origin/feature/x")
	Check ($r.Exit -eq 2 -and -not $r.Log) "-BaseBranch is refused for an existing worktree"

	$r = Invoke-Tool "StartWorker.ps1" @("-Task", "task_1", "-RetryOf", "ctx_1", "-Worktree", "path:C:/w")
	Check ($r.Exit -eq 0 -and $r.Output -match "retried" -and $r.Log -match "--task task_1" -and $r.Log -match "--retry-of ctx_1" -and $r.Log -match "--agent claude" -and $r.Log -notmatch "--spec-file") "a retry names the failed Task instead of a spec (Orca: --retry-of needs --task)"

	foreach ($bad in @(
			@("-RetryOf", "ctx_1", "-Worktree", "path:C:/w"),
			@("-Task", "task_1", "-Worktree", "path:C:/w"),
			@("-SpecFile", $specFile, "-Task", "task_1", "-RetryOf", "ctx_1", "-Worktree", "path:C:/w"),
			@("-Task", "task_1", "-RetryOf", "ctx_1"),
			@()
		)) {
		$r = Invoke-Tool "StartWorker.ps1" $bad
		Check ($r.Exit -eq 2 -and -not $r.Log) "refused before orca: $($bad -join ' ')"
	}

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile)
	Check ($r.Exit -eq 2 -and -not $r.Log) "a new worktree needs -Name"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", (Join-Path $state "missing.md"), "-Name", "x")
	Check ($r.Exit -eq 2 -and -not $r.Log) "a missing spec file stops before orca"

	$empty = Join-Path $state "empty.md"
	Set-Content -LiteralPath $empty -Value "  " -Encoding utf8
	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $empty, "-Name", "x")
	Check ($r.Exit -eq 2 -and -not $r.Log) "an empty spec stops before orca"

	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "x", "-DryRun")
	Check ($r.Exit -eq 0 -and -not $r.Log -and $r.Output -match "テストの仕様") "-DryRun prints and does not call orca"

	$env:LOOPBGM_TEST_ORCA_START_EXIT = "5"
	$r = Invoke-Tool "StartWorker.ps1" @("-SpecFile", $specFile, "-Name", "x")
	$env:LOOPBGM_TEST_ORCA_START_EXIT = "0"
	Check ($r.Exit -eq 5) "the exit code of orca is returned (実際: $($r.Exit))"
}
finally {
	$env:PATH = $savedPath
	$env:ORCA_CLI_COMMAND = $savedCli
	Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

if ($failures.Count -gt 0) {
	Write-Host "$($failures.Count) 件失敗" -ForegroundColor Red
	exit 1
}
Write-Host "すべて成功"
exit 0
