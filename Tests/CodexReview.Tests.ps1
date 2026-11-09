<#
.SYNOPSIS
	CodexReview.ps1 の目印の読み取りと、-SetStatus の省略の回帰テスト(#195)。本物の GitHub と Codex は呼ばない。

.DESCRIPTION
	前半は、スクリプトを実行せずに関数の定義だけを取り出して呼ぶ(判定、目印の書式、読み取り、FINDINGS の回数)。
	後半は、%TEMP% の使い捨てのリポジトリ(bare の origin に refs/heads/develop と refs/pull/7/head がある)の中に
	スクリプトをコピーし、PATH の先頭の偽の gh.ps1 と codex.ps1 で通しで実行する。偽物は呼ばれた内容をログに書く。
	実行の前に Get-Command で偽物が解決されることを確かめ、そうでなければ失敗する。

.PARAMETER ScriptPath
	テストするスクリプト。既定はリポジトリの CodexReview.ps1。

.EXAMPLE
	pwsh -NoProfile -File Tests/CodexReview.Tests.ps1
#>
[CmdletBinding()]
param(
	[string]$ScriptPath = (Join-Path $PSScriptRoot "..\CodexReview.ps1")
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptPath = (Resolve-Path $ScriptPath).Path

$failures = [System.Collections.Generic.List[string]]::new()
function Check([bool]$condition, [string]$message) {
	if ($condition) { Write-Host "  ok: $message" }
	else {
		Write-Host "  NG: $message" -ForegroundColor Red
		$failures.Add($message)
	}
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw "CodexReview.ps1 の構文エラー: $($parseErrors[0].Message)" }
$wanted = @("Get-ReviewVerdict", "Get-ReviewMarker", "Get-ReviewMarkers", "Find-ReusablePass", "Get-FindingsCount")
$functions = @($ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false) |
	Where-Object { $wanted -contains $_.Name })
foreach ($name in $wanted) {
	if (-not ($functions | Where-Object Name -eq $name)) { throw "CodexReview.ps1 に関数 $name がありません" }
}
foreach ($function in $functions) { . ([scriptblock]::Create($function.Extent.Text)) }

$passText = "問題は見つかりませんでした。"
$findingsText = "Review comment:`n`n- [P2] 例 — a.cpp:1-2`n  説明"

Write-Host "== Get-ReviewVerdict(既存の判定を弱めない) =="
Check ((Get-ReviewVerdict $passText) -eq "PASS") "no finding line and the phrase -> PASS"
Check ((Get-ReviewVerdict $findingsText) -eq "FINDINGS") "a finding line -> FINDINGS"
Check ((Get-ReviewVerdict "$findingsText`n$passText") -eq "FINDINGS") "a finding line wins over the phrase"
Check ((Get-ReviewVerdict "Full review comments:`n$passText") -eq "FINDINGS") "the findings heading wins over the phrase"
Check ((Get-ReviewVerdict "Reviewer failed to output a response.") -eq "UNKNOWN") "no phrase -> UNKNOWN"

Write-Host "== 目印の読み取り =="
$sha = "a" * 40
$other = "b" * 40
function New-ReviewComment([string]$Verdict, [string]$CommentSha, [string]$Base = "develop", [string]$Login = "me", [string]$Url = "u") {
	[pscustomobject]@{
		author = [pscustomobject]@{ login = $Login }
		url = $Url
		body = "## Codex レビュー`n`n本文`n`n---`nfooter`n" + (Get-ReviewMarker $Verdict $CommentSha $Base)
	}
}
Check ((Get-ReviewMarker "PASS" $sha "develop") -eq "<!-- codex-review verdict=pass sha=$sha base=develop -->") "marker format"
Check ($null -ne (Find-ReusablePass @(New-ReviewComment "PASS" $sha) "me" $sha "develop")) "PASS of this head"
Check ($null -eq (Find-ReusablePass @(New-ReviewComment "PASS" $other) "me" $sha "develop")) "PASS of another head does not count"
Check ($null -eq (Find-ReusablePass @(New-ReviewComment "PASS" $sha "main") "me" $sha "develop")) "PASS against another base does not count"
Check ($null -eq (Find-ReusablePass @(New-ReviewComment "PASS" $sha "develop" "someone") "me" $sha "develop")) "PASS written by someone else does not count"
Check ($null -eq (Find-ReusablePass @((New-ReviewComment "PASS" $sha), (New-ReviewComment "FINDINGS" $sha)) "me" $sha "develop")) "a later FINDINGS on the same head wins"
$pass = Find-ReusablePass @((New-ReviewComment "FINDINGS" $sha "develop" "me" "first"), (New-ReviewComment "PASS" $sha "develop" "me" "second")) "me" $sha "develop"
Check ($pass -and $pass.Url -eq "second") "a later PASS on the same head counts, with its URL"
$quoted = [pscustomobject]@{ author = [pscustomobject]@{ login = "me" }; url = "u"; body = "## Codex レビュー`n" + (Get-ReviewMarker "PASS" $sha "develop") + "`n`n- [P1] 指摘`n" }
Check ($null -eq (Find-ReusablePass @($quoted) "me" $sha "develop")) "a marker quoted in the middle of the body does not count"
$notReview = [pscustomobject]@{ author = [pscustomobject]@{ login = "me" }; url = "u"; body = "返信`n" + (Get-ReviewMarker "PASS" $sha "develop") }
Check ($null -eq (Find-ReusablePass @($notReview) "me" $sha "develop")) "a marker in another kind of comment does not count"
$crlf = New-ReviewComment "PASS" $sha
$crlf.body = $crlf.body.Replace("`n", "`r`n") + "`r`n"
Check ($null -ne (Find-ReusablePass @($crlf) "me" $sha "develop")) "CRLF line ends and a trailing newline are read"
Check ($null -eq (Find-ReusablePass @() "me" $sha "develop")) "no comments"
Check ($null -eq (Find-ReusablePass @(New-ReviewComment "PASS" $sha) "" $sha "develop")) "unknown viewer -> nothing counts"
$mixed = @((New-ReviewComment "FINDINGS" $sha), (New-ReviewComment "FINDINGS" $other), (New-ReviewComment "PASS" $sha), (New-ReviewComment "FINDINGS" $sha "develop" "someone"))
Check ((Get-FindingsCount $mixed "me") -eq 2) "FINDINGS are counted across heads, only mine"

Write-Host "== 通しの実行(偽の gh と codex) =="
$fakeGh = @'
# 偽の gh(テスト用)。状態は LOOPBGM_TEST_STATE のフォルダのファイルに置く
Add-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "gh.log") -Value "$args" -Encoding utf8
$comments = Join-Path $env:LOOPBGM_TEST_STATE "comments.json"
if ($args[0] -eq "repo" -and $args[1] -eq "view") { Write-Output $env:LOOPBGM_TEST_ORIGIN; exit 0 }
if ($args[0] -eq "api" -and $args[1] -eq "user") { Write-Output "me"; exit 0 }
if ($args[0] -eq "api" -and "$args" -match "protection/required_status_checks") {
	if ($env:LOOPBGM_TEST_UNPROTECTED -eq "1") { exit 1 }
	Write-Output "codex-review"; Write-Output "No hold label"; exit 0
}
# codex-review のステータスを覚える。LOOPBGM_TEST_STATUS_UNREADABLE=1 なら読めない
$statusFile = Join-Path $env:LOOPBGM_TEST_STATE "status.txt"
if ($args[0] -eq "api" -and "$args" -match "commits/\S+/status") {
	if ($env:LOOPBGM_TEST_STATUS_UNREADABLE -eq "1") { exit 1 }
	if (Test-Path $statusFile) { Get-Content -Raw $statusFile }
	exit 0
}
if ($args[0] -eq "api" -and "$args" -match "statuses/\S+ .*state=(\w+)") { Set-Content -NoNewline -LiteralPath $statusFile -Value $Matches[1]; exit 0 }
if ($args[0] -eq "api") { exit 0 }
if ($args[0] -eq "pr" -and $args[1] -eq "merge") { exit 0 }
if ($args[0] -eq "pr" -and $args[1] -eq "comment") {
	$file = $args[[array]::IndexOf($args, "--body-file") + 1]
	$list = @(Get-Content -Raw -Encoding utf8 $comments | ConvertFrom-Json)
	$list += [pscustomobject]@{ author = [pscustomobject]@{ login = "me" }; url = "https://example/c$($list.Count)"; body = (Get-Content -Raw -Encoding utf8 $file) }
	ConvertTo-Json -Depth 5 -InputObject @($list) | Set-Content -Encoding utf8 $comments
	Write-Output "https://example/c$($list.Count - 1)"
	exit 0
}
if ($args[0] -eq "pr" -and $args[1] -eq "view") {
	$fields = $args[[array]::IndexOf($args, "--json") + 1]
	if ($fields -eq "comments") {
		$list = @(Get-Content -Raw -Encoding utf8 $comments | ConvertFrom-Json)
		ConvertTo-Json -Depth 5 -InputObject ([pscustomobject]@{ comments = @($list) })
		exit 0
	}
	ConvertTo-Json -Depth 5 -InputObject ([pscustomobject]@{
		number = 7; title = "t"; url = "u"; state = "OPEN"; baseRefName = "develop"; headRefOid = $env:LOOPBGM_TEST_HEAD; mergeCommit = $null
	})
	exit 0
}
Write-Error "unexpected gh call: $args"
exit 1
'@
$fakeCodex = @'
# 偽の codex(テスト用)。呼ばれたことを記録し、LOOPBGM_TEST_REVIEW を出す
Add-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "codex.log") -Value "called" -Encoding utf8
# レビューの間にロックが開けないことを記録する
foreach ($file in Get-ChildItem -LiteralPath ([IO.Path]::GetTempPath()) -Filter "LoopBgmCodexReview-7-*.lock") {
	try { [IO.File]::Open($file.FullName, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None).Dispose(); $seen = "free" }
	catch { $seen = "held" }
	Add-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "lock.log") -Value $seen
}
# hold-file: worktreeのファイルを開いたままにして、git worktree remove を失敗させる
if ($env:LOOPBGM_TEST_CODEX_MODE -eq "hold-file") {
	$global:heldFile = [IO.File]::Open((Join-Path (Get-Location) "held.txt"), [IO.FileMode]::Create, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
}
# hang: 子プロセスの中で待つ(TaskStop などで親だけが強制終了され、子が残る場合の再現)
if ($env:LOOPBGM_TEST_CODEX_MODE -eq "hang") {
	pwsh -NoProfile -File (Join-Path $PSScriptRoot "hang-child.ps1")
}
Write-Output $env:LOOPBGM_TEST_REVIEW
exit 0
'@

$env:GIT_AUTHOR_NAME = "test"; $env:GIT_AUTHOR_EMAIL = "test@example.com"
$env:GIT_COMMITTER_NAME = "test"; $env:GIT_COMMITTER_EMAIL = "test@example.com"
$env:GIT_CONFIG_COUNT = "2"
$env:GIT_CONFIG_KEY_0 = "commit.gpgsign"; $env:GIT_CONFIG_VALUE_0 = "false"
$env:GIT_CONFIG_KEY_1 = "core.autocrlf"; $env:GIT_CONFIG_VALUE_1 = "false"

function Invoke-Git {
	$output = git @args 2>&1
	if ($LASTEXITCODE -ne 0) { throw "git $args に失敗しました: $output" }
	$output
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("loopbgm_codexreview_test_" + [guid]::NewGuid().ToString("N"))
$bin = Join-Path $root "bin"
$state = Join-Path $root "state"
$origin = Join-Path $root "origin.git"
$repo = Join-Path $root "repo"
$temp = Join-Path $root "tmp"
$savedPath = $env:PATH
$savedTemp = $env:TEMP, $env:TMP
$hangParent = $null
$hangChild = $null
try {
	New-Item -ItemType Directory -Path $bin, $state, $temp | Out-Null
	Set-Content -LiteralPath (Join-Path $bin "gh.ps1") -Value $fakeGh -Encoding utf8
	Set-Content -LiteralPath (Join-Path $bin "codex.ps1") -Value $fakeCodex -Encoding utf8

	Invoke-Git init -q --bare $origin | Out-Null
	Invoke-Git init -q -b develop $repo | Out-Null
	Copy-Item -LiteralPath $ScriptPath -Destination (Join-Path $repo "CodexReview.ps1")
	Invoke-Git -C $repo add . | Out-Null
	Invoke-Git -C $repo commit -q -m first | Out-Null
	Invoke-Git -C $repo push -q $origin develop | Out-Null
	Invoke-Git -C $repo commit -q --allow-empty -m change | Out-Null
	$head = (Invoke-Git -C $repo rev-parse HEAD).Trim()
	Invoke-Git -C $repo push -q $origin "HEAD:refs/pull/7/head" | Out-Null
	# CleanupMerged.ps1 も一緒に動かす(スクリプトのフォルダをリポジトリとして扱い、origin を読む)
	Copy-Item -LiteralPath (Join-Path (Split-Path $ScriptPath) "CleanupMerged.ps1") -Destination (Join-Path $repo "CleanupMerged.ps1")
	Invoke-Git -C $repo remote add origin $origin | Out-Null
	Invoke-Git -C $repo fetch -q origin | Out-Null
	Invoke-Git -C $repo branch -q -u origin/develop | Out-Null

	# ロックとworktreeはこのフォルダに作らせ、残りを調べる
	$env:TEMP = $temp
	$env:TMP = $temp
	$env:PATH = "$bin;$savedPath"
	$env:LOOPBGM_TEST_STATE = $state
	$env:LOOPBGM_TEST_ORIGIN = $origin
	$env:LOOPBGM_TEST_HEAD = $head
	foreach ($tool in "gh", "codex") {
		if ((Get-Command $tool).Source -notlike "$bin*") { throw "偽の $tool が解決されません: $((Get-Command $tool).Source)" }
	}
	$script = Join-Path $repo "CodexReview.ps1"

	function Set-Comments($list) {
		ConvertTo-Json -Depth 5 -InputObject @($list) | Set-Content -Encoding utf8 (Join-Path $state "comments.json")
		Remove-Item -ErrorAction SilentlyContinue (Join-Path $state "status.txt")
	}
	function Invoke-Review([string[]]$Arguments, [string]$Review) {
		Remove-Item -ErrorAction SilentlyContinue (Join-Path $state "gh.log"), (Join-Path $state "codex.log")
		$env:LOOPBGM_TEST_REVIEW = $Review
		$output = & pwsh -NoProfile -File $script -Pr 7 @Arguments 2>&1 | Out-String
		$ghLog = if (Test-Path (Join-Path $state "gh.log")) { Get-Content -Raw -Encoding utf8 (Join-Path $state "gh.log") } else { "" }
		[pscustomobject]@{
			Exit = $LASTEXITCODE
			Output = $output
			Codex = Test-Path (Join-Path $state "codex.log")
			Success = $ghLog -match "statuses/$head .*state=success"
			Failure = $ghLog -match "statuses/$head .*state=failure"
			Merge = $ghLog -match "pr merge 7 --auto --merge"
			Comment = $ghLog -match "pr comment 7"
			Gh = $ghLog
		}
	}
	function Read-LastBody { (@(Get-Content -Raw -Encoding utf8 (Join-Path $state "comments.json") | ConvertFrom-Json))[-1].body }

	Set-Comments @()
	$r = Invoke-Review @("-Post") $passText
	Check ($r.Exit -eq 0 -and $r.Codex -and $r.Comment) "-Post runs Codex and comments"
	Check ((Read-LastBody) -match "(?m)^<!-- codex-review verdict=pass sha=$head base=develop -->\s*\z") "the PASS comment ends with the marker"
	Check ($r.Output -match "FINDINGSの回数: 0") "-Post prints the FINDINGS count"
	Check (-not $r.Success -and -not $r.Merge) "-Post alone sets no status and schedules no merge"

	$r = Invoke-Review @("-SetStatus") "this must not be read"
	Check ($r.Exit -eq 0 -and -not $r.Codex) "-SetStatus with a PASS of this head does not run Codex"
	Check ($r.Success -and $r.Merge) "-SetStatus with a PASS sets success and schedules the merge"
	Check ($r.Output -match "判定: PASS") "prints the verdict"
	Check ($r.Gh -match "target_url=https://example/c0") "the status links to the PASS comment"
	$left = Invoke-Git -C $repo for-each-ref "refs/codex-review"
	Check (-not $left) "no refs are left behind when the review is skipped"

	$r = Invoke-Review @("-SetStatus", "-Post") "this must not be read"
	Check (-not $r.Codex -and -not $r.Comment -and $r.Merge) "-Post -SetStatus with a PASS does not comment again"

	$r = Invoke-Review @("-SetStatus", "-ForceReview") $passText
	Check ($r.Codex -and $r.Success -and $r.Merge) "-ForceReview runs Codex even with a PASS"

	Set-Comments @()
	$r = Invoke-Review @("-SetStatus") $passText
	Check ($r.Codex -and $r.Success -and $r.Merge) "-SetStatus without a marker reviews as before"

	$r = Invoke-Review @("-SetStatus", "-Post") $findingsText
	Check ($r.Codex -and $r.Failure -and -not $r.Merge) "findings set failure and schedule nothing"
	Check ((Read-LastBody) -match "(?m)^<!-- codex-review verdict=findings sha=$head base=develop -->\s*\z") "the FINDINGS comment ends with the marker"
	Check ($r.Output -match "FINDINGSの回数: 1" -and $r.Output -notmatch "相談") "the first FINDINGS does not ask to consult"

	$r = Invoke-Review @("-SetStatus") "Reviewer failed to output a response."
	Check ($r.Codex -and $r.Failure -and -not $r.Merge) "an unreadable review sets failure"

	$r = Invoke-Review @("-Post") "Reviewer failed to output a response."
	Check ((Read-LastBody) -notmatch "codex-review verdict") "an unreadable review gets no marker"

	foreach ($count in 2, 3) { $r = Invoke-Review @("-Post") $findingsText }
	Check ($r.Output -match "FINDINGSの回数: 3" -and $r.Output -notmatch "相談") "3 FINDINGS do not ask to consult yet"
	$r = Invoke-Review @("-Post") $findingsText
	Check ($r.Output -match "FINDINGSの回数: 4" -and $r.Output -match "コーディネーターに ask で相談") "over 3 FINDINGS asks to consult the coordinator"
	$r = Invoke-Review @("-Post", "-ForceReview") $passText
	Check ($r.Output -match "FINDINGSの回数: 4" -and $r.Output -notmatch "相談") "a PASS does not ask to consult, however many FINDINGS came before"

	# あとから出た FINDINGS があれば、前の PASS を使わない
	Set-Comments @()
	$r = Invoke-Review @("-Post") $passText
	$r = Invoke-Review @("-Post", "-ForceReview") $findingsText
	$r = Invoke-Review @("-SetStatus") $findingsText
	Check ($r.Codex -and $r.Failure -and -not $r.Merge) "a later FINDINGS on this head means a new review"

	# -Post なしのレビューは目印を残さず、failure のステータスだけを残す。これを古い PASS で上書きしない(PR #196 の Codex の指摘)
	Set-Comments @()
	Invoke-Review @("-Post") $passText | Out-Null
	$r = Invoke-Review @("-SetStatus", "-ForceReview") $findingsText
	Check ($r.Failure -and -not $r.Merge) "a forced review without -Post sets failure"
	$r = Invoke-Review @("-SetStatus") $findingsText
	Check ($r.Codex -and $r.Failure -and -not $r.Merge) "a failure status on this head is not overwritten by an older PASS"
	$r = Invoke-Review @("-SetStatus") $passText
	Check ($r.Codex -and $r.Success -and $r.Merge) "a new review can clear the failure"
	$r = Invoke-Review @("-SetStatus") "this must not be read"
	Check (-not $r.Codex -and $r.Merge) "the PASS is reused again after the failure is cleared"

	# ステータスを読めないときは、PASS を使わない
	$env:LOOPBGM_TEST_STATUS_UNREADABLE = "1"
	$r = Invoke-Review @("-SetStatus") $passText
	$env:LOOPBGM_TEST_STATUS_UNREADABLE = ""
	Check ($r.Codex -and $r.Merge) "an unreadable status means a new review"

	# 他人が書いた PASS の目印では通らない(public のリポジトリでは誰でもコメントできる)
	$forged = [pscustomobject]@{ author = [pscustomobject]@{ login = "someone" }; url = "x"; body = "## Codex レビュー`n`n" + (Get-ReviewMarker "PASS" $head "develop") }
	Set-Comments @($forged)
	$r = Invoke-Review @("-SetStatus") $findingsText
	Check ($r.Codex -and -not $r.Merge) "a marker written by someone else is ignored"

	# 目印があっても、保護の確認は省かない
	Set-Comments @()
	Invoke-Review @("-Post") $passText | Out-Null
	$env:LOOPBGM_TEST_UNPROTECTED = "1"
	$r = Invoke-Review @("-SetStatus") $passText
	$env:LOOPBGM_TEST_UNPROTECTED = ""
	Check ($r.Exit -ne 0 -and -not $r.Codex -and -not $r.Success -and -not $r.Merge -and $r.Output -match "ブランチ保護") "the protection check still stops a PASS on an unprotected base"

	Write-Host "== ロックと後始末 =="
	function Get-RunLeftovers {
		$items = @(Get-ChildItem -LiteralPath $temp -Filter "LoopBgmCodexReview-*" | ForEach-Object { $_.Name })
		$items += @(Invoke-Git -C $repo for-each-ref --format='%(refname)' "refs/codex-review")
		return @($items | Where-Object { $_ })
	}
	function Invoke-RepoCleanup { & pwsh -NoProfile -File (Join-Path $repo "CleanupMerged.ps1") 2>&1 | Out-String }
	function Test-LockHeld([string]$path) {
		try { [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None).Dispose(); return $false }
		catch { return $true }
	}
	$lockLog = Join-Path $state "lock.log"

	# ここまでの通しの実行(省略、保護で止まる、指摘あり)のどれも残さない
	Check ((Get-RunLeftovers).Count -eq 0) "none of the runs above left a lock, worktree, log or ref"

	Remove-Item -ErrorAction SilentlyContinue $lockLog
	Set-Comments @()
	$r = Invoke-Review @() $passText
	Check ((Get-Content -LiteralPath $lockLog) -eq "held") "the lock is held while Codex runs"
	Check ((Get-RunLeftovers).Count -eq 0) "a finished review leaves nothing"

	# refを取得する前に失敗したときも、ロックを残さない
	$env:LOOPBGM_TEST_ORIGIN = Join-Path $root "missing.git"
	$r = Invoke-Review @() $passText
	$env:LOOPBGM_TEST_ORIGIN = $origin
	Check ($r.Exit -ne 0 -and $r.Output -match "git fetch に失敗" -and (Get-RunLeftovers).Count -eq 0) "a failed fetch leaves no lock"

	# worktreeを消せなかったときは、閉じたロックを残し、次の CleanupMerged.ps1 に任せる
	$env:LOOPBGM_TEST_CODEX_MODE = "hold-file"
	$r = Invoke-Review @() $passText
	$env:LOOPBGM_TEST_CODEX_MODE = ""
	Check ($r.Output -match "一時worktreeを削除できませんでした") "a worktree that cannot be removed is reported"
	$lockFile = @(Get-ChildItem -LiteralPath $temp -Filter "LoopBgmCodexReview-7-*.lock")
	Check ($lockFile.Count -eq 1 -and -not (Test-LockHeld $lockFile[0].FullName)) "the lock file stays, closed"
	$cleanup = Invoke-RepoCleanup
	Check ($cleanup -notmatch "WARNING" -and (Get-RunLeftovers).Count -eq 0) "CleanupMerged removes what that run left"

	# 親だけが強制終了され(finally が走らない)、子が残っている間は、次の実行が触らない
	$childPid = Join-Path $state "child.pid"
	Set-Content -LiteralPath (Join-Path $bin "hang-child.ps1") -Value 'Set-Content -LiteralPath (Join-Path $env:LOOPBGM_TEST_STATE "child.pid") -Value $PID; Start-Sleep -Seconds 120'
	$env:LOOPBGM_TEST_CODEX_MODE = "hang"
	$hangParent = Start-Process pwsh -PassThru -WindowStyle Hidden -ArgumentList "-NoProfile -File `"$script`" -Pr 7"
	$env:LOOPBGM_TEST_CODEX_MODE = ""
	$deadline = [DateTime]::UtcNow.AddSeconds(60)
	while (-not ((Test-Path -LiteralPath $childPid) -and (Get-Content -LiteralPath $childPid))) {
		if ([DateTime]::UtcNow -ge $deadline) { throw "偽の codex の子プロセスが起動しませんでした。" }
		Start-Sleep -Milliseconds 200
	}
	$hangChild = Get-Process -Id ([int](Get-Content -LiteralPath $childPid))
	Stop-Process -Id $hangParent.Id -Force
	$null = $hangParent.WaitForExit(10000)
	$lockFile = @(Get-ChildItem -LiteralPath $temp -Filter "LoopBgmCodexReview-7-*.lock")
	Check ($lockFile.Count -eq 1 -and (Test-LockHeld $lockFile[0].FullName)) "the surviving child still holds the inherited lock"
	$cleanup = Invoke-RepoCleanup
	Check ($cleanup -match "レビューの実行中" -and $cleanup -notmatch "WARNING") "CleanupMerged leaves a run whose child is alive"
	$workFolder = $lockFile[0].FullName -replace '\.lock$', ''
	$refCount = @(Invoke-Git -C $repo for-each-ref "refs/codex-review").Count
	Check ((Test-Path -LiteralPath $workFolder) -and $refCount -eq 2) "the worktree and refs of that run are untouched"
	Stop-Process -Id $hangChild.Id -Force
	$null = $hangChild.WaitForExit(10000)
	Check (-not (Test-LockHeld $lockFile[0].FullName)) "the lock is free once the child ends"
	$cleanup = Invoke-RepoCleanup
	Check ($cleanup -notmatch "WARNING" -and (Get-RunLeftovers).Count -eq 0) "CleanupMerged removes the killed run after the child ended"
}
finally {
	$env:PATH = $savedPath
	$env:TEMP, $env:TMP = $savedTemp
	foreach ($process in $hangChild, $hangParent) {
		if ($process -and -not $process.HasExited) {
			Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
			$null = $process.WaitForExit(10000)
		}
	}
	Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

if ($failures.Count -gt 0) {
	Write-Host "$($failures.Count) 件失敗" -ForegroundColor Red
	exit 1
}
Write-Host "すべて成功"
exit 0
