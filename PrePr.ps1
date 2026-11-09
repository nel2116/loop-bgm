<#
.SYNOPSIS
	PR を作る前に、変更したファイルに合う検査とテストを実行し、自己点検の項目を出すスクリプト。
	DXForgeEX の PrePr.ps1 を loop-bgm(Python)向けに作り直したもの。

.DESCRIPTION
	-Base(既定 origin/develop)との差分のファイルから、実行するものを決める。
	- python Tests/check_conventions.py と ruff は常に実行する。
	- .py か pyproject.toml を変更したら pytest(サンプルの要らないテストすべて)。
	- .ps1 を変更したら、そのスクリプトのテスト(下の表)。
	実行は最初の失敗で止まる。成功したステップは 1 行だけ、失敗したステップは出力の末尾だけを出す。

	すべて通ったら、git rev-parse --git-path loopbgm-prepr-stamp の場所(worktree ごと)に HEAD の sha を書く。
	Tests/guard_review_flow.py(PreToolUse フック)は、この sha が HEAD と違うときの gh pr create を止める。
	コミットしていない変更(追跡中のファイル)があると、スタンプと確かめた内容が食い違うので実行しない。

.PARAMETER Base
	比べる相手。既定は origin/develop(実行の前に fetch する)。ないときは HEAD のすべての追跡ファイルを対象にする。

.EXAMPLE
	./PrePr.ps1
#>
[CmdletBinding()]
param(
	[string]$Base = "origin/develop"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$StampName = "loopbgm-prepr-stamp"
$py = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $py)) { Write-Host "先に ./setup.ps1 を実行してください"; exit 1 }

$scriptTests = @{
	"CleanupMerged.ps1" = "pwsh -NoProfile -File Tests/CleanupMerged.Tests.ps1"
	"CodexReview.ps1"   = "pwsh -NoProfile -File Tests/CodexReview.Tests.ps1"
	"StartWorker.ps1"   = "pwsh -NoProfile -File Tests/WorkerTools.Tests.ps1"
	"WorkerStatus.ps1"  = "pwsh -NoProfile -File Tests/WorkerTools.Tests.ps1"
}

if (git status --porcelain --untracked-files=no) {
	Write-Host "コミットしていない変更があります。コミットしてから実行してください。"
	exit 1
}

git fetch -q origin 2>$null
$null = git rev-parse --verify --quiet $Base
if ($LASTEXITCODE -eq 0) {
	$files = @(git diff --name-only "$(git merge-base $Base HEAD)" HEAD)
}
else {
	Write-Host "($Base がないので、追跡中のファイルすべてを対象にします)"
	$files = @(git ls-files)
}

$steps = [System.Collections.Generic.List[string]]::new()
$steps.Add("python Tests/check_conventions.py")
$steps.Add("$py -m ruff check .")
if ($files | Where-Object { $_ -match '\.py$' -or $_ -eq "pyproject.toml" }) { $steps.Add("$py -m pytest -q") }
foreach ($f in $files) {
	if ($scriptTests.ContainsKey($f) -and $scriptTests[$f] -notin $steps) { $steps.Add($scriptTests[$f]) }
	if ($f -match '^Tests/.*\.Tests\.ps1$' -and (Test-Path $f)) {
		$cmd = "pwsh -NoProfile -File $f"
		if ($cmd -notin $steps) { $steps.Add($cmd) }
	}
}

$stamp = (git rev-parse --git-path $StampName).Trim()
Remove-Item -LiteralPath $stamp -ErrorAction SilentlyContinue
foreach ($step in $steps) {
	$out = & pwsh -NoProfile -Command $step 2>&1
	if ($LASTEXITCODE -ne 0) {
		Write-Host "失敗: $step"
		$out | Select-Object -Last 30 | ForEach-Object { Write-Host "  $_" }
		exit 1
	}
	Write-Host "ok: $step"
}

Write-Host ""
Write-Host "自己点検(PR 本文の「自己点検」に、それぞれ何を確かめたかを書く):"
Write-Host "- 新しい振る舞いにテストがあるか。テストは音源なし(合成音)で動くか"
Write-Host "- ユーザーに見えるエラーは日本語で、パートと小節を示しているか"
Write-Host "- 書き出す音が変わるなら、PR 本文に「試聴メモ」を書いたか"
Write-Host "- 振る舞いを変えたなら、docs/ と AGENTS.md の該当箇所を同じ PR で直したか"
Write-Host "- 音声ファイルや音源をコミットしていないか"

$head = (git rev-parse HEAD).Trim()
[System.IO.File]::WriteAllText([System.IO.Path]::Combine((Get-Location).Path, $stamp), "$head`n", [System.Text.UTF8Encoding]::new($false))
Write-Host ""
Write-Host "スタンプを書きました: $head"
