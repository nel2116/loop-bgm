<#
.SYNOPSIS
	Orca の Run の各ワーカーが生きているかを一覧にするスクリプト(#195)。

.DESCRIPTION
	worker-show の state: ready や worker-list の liveness では、プロセスが終わっていても分からない
	(worker-list の liveness は構造化モードでは unverifiable のまま)。send は終了したワーカーにも ok を返す。
	そのため、worker-read --json の status.terminal と status.liveness を読む(週間上限で終了したワーカーに
	約 11 時間気づかなかった、#195)。

	terminal が running でない未完了のワーカーを、目立たせて最後にまとめる。worker-list が返す next と
	attention も表示する。これは調べるための一覧で、ここから自動で止めたり起動し直したりはしない。
	沈黙や unknown・unverifiable だけでは終了の証拠にならない(Orca のガイド、#7)。次の行動は next に従い、
	なければ worker-show と Orca の復旧ガイド(recovery-and-cleanup.md)で確かめる。

	orca は ORCA_CLI_COMMAND があればその実行ファイル、なければ PATH の orca を使う。

.PARAMETER Run
	Run の ID。省略すると、このコーディネーターに結び付いている Run。

.PARAMETER Json
	JSON で出す。

.EXAMPLE
	./WorkerStatus.ps1 -Run run_2a14a3a681fb
#>
[CmdletBinding()]
param(
	[string]$Run,
	[switch]$Json
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$orca = if ($env:ORCA_CLI_COMMAND) { $env:ORCA_CLI_COMMAND } else { "orca" }

function Invoke-OrcaJson([string[]]$Arguments) {
	$output = & $orca orchestration @Arguments --json 2>$null
	if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
	try {
		$parsed = ($output | Out-String) | ConvertFrom-Json
	}
	catch {
		return $null
	}
	if (-not $parsed.ok) { return $null }
	return $parsed.result
}

if (-not (Get-Command $orca -ErrorAction SilentlyContinue)) {
	Write-Host "orca が見つかりません: $orca"
	exit 1
}

$workers = [System.Collections.Generic.List[object]]::new()
$cursor = $null
do {
	$listArgs = @("worker-list", "--limit", "100")
	if ($Run) { $listArgs += @("--run", $Run) }
	if ($cursor) { $listArgs += @("--cursor", $cursor) }
	$page = Invoke-OrcaJson $listArgs
	if (-not $page) {
		Write-Host "worker-list を読めませんでした(Run が結び付いていなければ -Run で指定してください)。"
		exit 1
	}
	foreach ($worker in @($page.workers)) { if ($worker) { $workers.Add($worker) } }
	$cursor = $page.nextCursor
} while ($cursor)

$rows = foreach ($worker in $workers) {
	# 解放済みのワーカーのプロセスは調べるまでもない(読むのも省く)
	$terminal = "released"
	$liveness = "-"
	if ($worker.terminalState -ne "released") {
		$read = Invoke-OrcaJson @("worker-read", "--dispatch", $worker.dispatchId, "--limit", "1")
		$terminal = if ($read -and $read.status.terminal) { $read.status.terminal } else { "unknown" }
		$liveness = if ($read -and $read.status.liveness) { $read.status.liveness } else { "unknown" }
	}
	[pscustomobject]@{
		Dispatch = $worker.dispatchId
		Task = $worker.taskId
		State = $worker.state
		Outcome = $worker.outcome
		Terminal = $terminal
		Liveness = $liveness
		TerminalState = $worker.terminalState
		Next = $worker.next
		Attention = @($worker.attention) -join ","
		Exited = $terminal -eq "exited"
		# 仕事が終わっていないのにプロセスがない、または確かめられない
		NeedsAttention = ($worker.outcome -eq "in_progress") -and ($terminal -notin "running") -and ($worker.terminalState -ne "released")
	}
}
$rows = @($rows)

if ($Json) {
	ConvertTo-Json -Depth 3 -InputObject $rows
	exit 0
}

foreach ($row in $rows) {
	$line = "{0,-20} state={1,-10} outcome={2,-12} terminal={3,-9} liveness={4,-8} {5}" -f $row.Dispatch, $row.State, $row.Outcome, $row.Terminal, $row.Liveness, $row.TerminalState
	if ($row.Attention) { $line += " attention=$($row.Attention)" }
	if ($row.Next) { $line += " next=$(ConvertTo-Json -Compress -Depth 5 -InputObject $row.Next)" }
	if ($row.Exited) { Write-Host "*** EXITED *** $line" -ForegroundColor Red }
	else { Write-Host "               $line" }
}
$attention = @($rows | Where-Object NeedsAttention)
$exited = @($rows | Where-Object Exited)
Write-Host "ワーカー $($rows.Count) 件、exited $($exited.Count) 件、未完了で動いていると確かめられないもの $($attention.Count) 件"
foreach ($row in $attention) {
	Write-Host "要確認: $($row.Dispatch)(terminal=$($row.Terminal))。これだけでは終了の証拠になりません。next があればそれに従い、なければ worker-show で確かめて、止める・再試行するかはユーザーに相談してください(Orca の復旧ガイド recovery-and-cleanup.md)。" -ForegroundColor Red
}
exit 0
