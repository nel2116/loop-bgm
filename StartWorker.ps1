<#
.SYNOPSIS
	共通のルール(docs/dev/WorkerRules.md)と仕様を必ず連結して、Orca のワーカーを起動するスクリプト(#195)。

.DESCRIPTION
	orca orchestration worker-start を包む。コーディネーターが共通のルールを貼り忘れることと、小さな仕事に
	大きなモデルを使うことを防ぐ。orca の出力と終了コードをそのまま返す。

	起動し直すときは 2 通りある。
	- -Task と -RetryOf: 失敗した Task をそのまま再試行する。Orca は --retry-of に --task を求め、仕様は Task に
	  入っているので -SpecFile は渡せない。worktree は引き継がれないので -Worktree も指定する。
	- -SpecFile(引き継ぎを書いた仕様)と -Worktree path:<パス>: 新しい Task として同じ worktree で続ける。

.PARAMETER SpecFile
	タスクの仕様のファイル(UTF-8)。-RetryOf のとき以外は必須。

.PARAMETER Size
	normal(既定)または small。small は --model claude-sonnet-5-5 を付ける。

.PARAMETER Name
	新しい worktree の名前(例: issue-195-review-flow)。

.PARAMETER Worktree
	--worktree に渡す値。既定は new-top-level。既存の worktree(path:...、current など)を選ぶと、
	worktree を作るときの引数(--name、--setup、--base-branch)は付けない。

.PARAMETER BaseBranch
	新しい worktree の起点(--base-branch)。既定は origin/develop。渡さないと Orca はリポジトリの既定のブランチ
	(main)から作るので、ワーカーの最初の確認(develop を含むか)が失敗する。

.PARAMETER Run
	Run の ID。省略すると、このコーディネーターに結び付いている Run。

.PARAMETER Task
	-RetryOf で再試行する、失敗した Task の ID(--task)。

.PARAMETER RetryOf
	再試行するときの、前の Dispatch の ID(--retry-of)。-Task と一緒に指定する。

.PARAMETER DryRun
	実行せず、orca の引数と連結した仕様を表示する。

.EXAMPLE
	./StartWorker.ps1 -SpecFile $env:TEMP\spec.md -Name issue-200-foo -Size small
#>
[CmdletBinding()]
param(
	[string]$SpecFile,

	[ValidateSet("normal", "small")]
	[string]$Size = "normal",

	[string]$Name,

	[string]$Worktree = "new-top-level",

	[string]$BaseBranch = "origin/develop",

	[string]$Run,

	[string]$Task,

	[string]$RetryOf,

	[switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$SmallModel = "claude-sonnet-5-5"
$rulesPath = Join-Path $PSScriptRoot "docs/dev/WorkerRules.md"

$isRetry = [bool]$RetryOf
if ([bool]$Task -ne $isRetry -or ($isRetry -and $SpecFile) -or (-not $isRetry -and -not $SpecFile)) {
	Write-Host "-SpecFile か、-Task と -RetryOf の組み合わせのどちらかを指定してください(--retry-of には失敗した Task が要り、仕様は渡せません)。"
	exit 2
}
$isNewWorktree = $Worktree -like "new-*"
if ($PSBoundParameters.ContainsKey("BaseBranch") -and -not $isNewWorktree) {
	Write-Host "-BaseBranch は新しい worktree のときだけ指定できます。"
	exit 2
}
if ($isRetry -and $isNewWorktree) {
	Write-Host "再試行は worktree を引き継がないので、-Worktree path:<パス> で前の worktree を指定してください。"
	exit 2
}

if (-not $isRetry) {
	foreach ($path in $rulesPath, $SpecFile) {
		if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
			Write-Host "ファイルがありません: $path"
			exit 2
		}
	}
	$rules = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $rulesPath).Path, [System.Text.Encoding]::UTF8)
	# 文書の見直した日(#237)はワーカーへの仕様に要らないので除く
	$rules = [regex]::Replace($rules, '(?m)^<!-- last-reviewed: [^\r\n]*\r?\n', '').Trim()
	$spec = [System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $SpecFile).Path, [System.Text.Encoding]::UTF8).Trim()
	if (-not $rules -or -not $spec) {
		Write-Host "共通のルールまたは仕様が空です。"
		exit 2
	}
}

if ($isNewWorktree -and -not $Name) {
	Write-Host "新しい worktree には -Name が要ります(例: issue-200-foo)。"
	exit 2
}

$arguments = @("orchestration", "worker-start", "--agent", "claude", "--worktree", $Worktree)
if ($isNewWorktree) { $arguments += @("--name", $Name, "--base-branch", $BaseBranch, "--setup", "run") }
if ($Size -eq "small") { $arguments += @("--model", $SmallModel) }
if ($Run) { $arguments += @("--run", $Run) }
if ($isRetry) { $arguments += @("--task", $Task, "--retry-of", $RetryOf) }

if ($DryRun) {
	if ($isRetry) {
		Write-Output "orca $($arguments -join ' ')"
	}
	else {
		Write-Output "orca $($arguments -join ' ') --spec-file <連結した仕様>"
		Write-Output "$rules`n`n$spec`n"
	}
	exit 0
}

if (-not (Get-Command orca -ErrorAction SilentlyContinue)) {
	Write-Host "orca が見つかりません。"
	exit 1
}
if ($isRetry) {
	& orca @arguments
	exit $LASTEXITCODE
}
$combined = "$rules`n`n$spec`n"
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("loopbgm_worker_spec_" + [guid]::NewGuid().ToString("N") + ".md")
try {
	[System.IO.File]::WriteAllText($temp, $combined, [System.Text.UTF8Encoding]::new($false))
	& orca @arguments --spec-file $temp
	exit $LASTEXITCODE
}
finally {
	Remove-Item -LiteralPath $temp -ErrorAction SilentlyContinue
}
