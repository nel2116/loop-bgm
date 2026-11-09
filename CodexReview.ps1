<#
.SYNOPSIS
	PRの変更を Codex CLI (codex review) でレビューし、結果を表示する(-Post でPRにコメントする)スクリプト。

.DESCRIPTION
	実装したエージェントとは別のモデルに差分を見せ、別の視点からの指摘を得るためのもの。
	PRのhead(refs/pull/<番号>/head)を一時フォルダに使い捨てのworktreeとして展開し、その中で
	codex review を実行する。終わったら(失敗しても)worktreeは削除する。作業中のworktreeには触らない。
	プロセスが強制終了されると後始末が走らないので、実行中は %TEMP% の LoopBgmCodexReview-<番号>-<ID>.lock を
	排他で開いて持つ。子プロセス(codex)にも継承させるので、ロックを開けるなら誰も使っていない。
	残ったものは CleanupMerged.ps1 が、ロックを開けたものだけ片付ける。

	注意点:
	- Windowsでは Codex のサンドボックスが無効("Windows sandbox selection: disabled")だと、読み取り専用の
	  レビューでもコマンドの実行がすべて "blocked by policy" で拒否され、差分を読めないまま終わる。
	  そのため呼び出しごとに -c windows.sandbox="unelevated" を渡す(~/.codex/config.toml は変更しない)。
	- codex review は --base とカスタム指示を同時に指定できないため、差分の範囲は指示の中で指定する。
	- マージ済みのPRは、マージコミットの2つの親(マージ直前のbaseとPRのhead)を比べ、各指摘が今のbaseでも
	  残っているかもCodexに確かめさせる(merge commitでマージされたPRのみ対応)。
	- 所要時間の目安は1PRあたり1〜数分。ビルドやテストは行わない(読み取り専用)ため、CIの代わりにはならない。

.PARAMETER Pr
	レビューするPRの番号。

.PARAMETER Post
	レビュー結果をPRにコメントとして投稿する。指定しない場合は表示するだけ。

.PARAMETER Effort
	Codexの推論の強さ(model_reasoning_effort)。既定値: high。

.PARAMETER SetStatus
	マージの関門として、レビューしたコミットにコミットステータス codex-review を付ける。
	Codexの出力に指摘("- [P0〜P3] ..." の行)がなければ success を付けて自動マージ(gh pr merge --auto --merge)を
	予約し、指摘があれば重大度を問わず failure を付ける。向き先のブランチ保護が codex-review と No hold label を
	必須にしていないPRには使えない(レビューの前に確かめて止まる)。developのブランチ保護は CI・hold・codex-review の
	成功を必須にしているため、CI と codex-review がそろった時点でGitHubがマージする。保護が Merge approved も
	必須にしているときは、人がPRに merge-ok ラベルを付けて承認するまでマージされない(#160。今の develop では
	必須にしていない)。エージェントは merge-ok を付けない。
	ステータスはコミットに付くので、修正をpushすると外れ、再レビューで success になるまでマージされない。
	merge-ok も push で外れる(.github/workflows/pr-automation.yml)。
	PRの完了条件(GUIでの確認など)がそろってから、コーディネーターが指定すること。マージ済みのPRには使えない。
	今のheadのPASSの目印(下の -Post)がPRにあれば、Codexを実行せずにステータスを設定する(#195)。
	ただし、そのheadの codex-review がすでに failure か、読めないときはレビューする(-Post なしのレビューは
	目印を残さないので、そのfailureを古いPASSで上書きしない)。

.PARAMETER ForceReview
	-SetStatus で、PASSの目印があってもレビューをやり直す。

.NOTES
	-Post は、PASSとFINDINGSのコメントの最後の行に目印を入れる(#195):
	<!-- codex-review verdict=<pass|findings> sha=<40桁> base=<向き先> -->
	目印として読むのは、gh でログインしているユーザーが書いた「## Codex レビュー」で始まるコメントの最後の行だけ
	(ほかの人のコメントや、レビューの本文に引用された目印では通らない)。同じheadと向き先に複数あれば、最後のものを使う。

.EXAMPLE
	./CodexReview.ps1 -Pr 52
	PR #52 をレビューして結果を表示する。

.EXAMPLE
	./CodexReview.ps1 -Pr 52 -Post
	PR #52 をレビューして結果をPRにコメントする。

.EXAMPLE
	./CodexReview.ps1 -Pr 52 -Post -SetStatus
	PR #52 をレビューしてコメントし、指摘がなければ codex-review を success にして自動マージを予約する
	(保護が Merge approved を必須にしているときは、人が merge-ok ラベルを付けるとマージされる)。
#>
[CmdletBinding()]
param(
	[Parameter(Mandatory = $true)]
	[int]$Pr,

	[switch]$Post,

	[ValidateSet("low", "medium", "high", "xhigh")]
	[string]$Effort = "high",

	[switch]$SetStatus,

	[switch]$ForceReview
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot

# FINDINGS がこの回数を超えたら、直し続けず相談するよう促す(ship-pr スキルの「指摘が収束しないとき」)
$FindingsConsultLimit = 3

# codex review の出力から判定する。
# codex review は独自の出力形式に従い、カスタム指示で最後の行の書式を指定しても守らない。
# 指摘は必ず "- [P1] 見出し — ファイル:行" の形の行で出る("Full review comments:" / 1件なら "Review comment:" の下)ので、
# その行が1つでもあれば指摘あり(重大度を問わない)。指摘なしとするのは、その行がなく、かつ指示した
# 「問題は見つかりませんでした」を含むときだけ(レビュー不能のメッセージなどを指摘なしと取り違えない)
function Get-ReviewVerdict([string]$Review) {
	if ($Review -match '(?m)^\s*-\s*\[P[0-3]\]' -or $Review -match '(?m)^(Full review comments|Review comments?):') { return "FINDINGS" }
	if ($Review -match '問題は見つかりませんでした') { return "PASS" }
	return "UNKNOWN"
}

# PRのコメントの最後の行に入れる、機械で読める目印
function Get-ReviewMarker([string]$Verdict, [string]$Sha, [string]$Base) {
	return "<!-- codex-review verdict=$($Verdict.ToLowerInvariant()) sha=$Sha base=$Base -->"
}

# gh pr view --json comments のコメントから、目印を時系列で取り出す。
# ログインしているユーザーの、「## Codex レビュー」で始まるコメントの最後の行だけを読む
function Get-ReviewMarkers($Comments, [string]$Viewer) {
	foreach ($comment in @($Comments)) {
		if (-not $comment -or -not $Viewer -or $comment.author.login -ne $Viewer) { continue }
		$match = [regex]::Match([string]$comment.body, '\A## Codex レビュー\r?\n[\s\S]*\n<!-- codex-review verdict=(pass|findings) sha=([0-9a-f]{40}) base=(\S+) -->\s*\z')
		if ($match.Success) {
			[pscustomobject]@{ Verdict = $match.Groups[1].Value; Sha = $match.Groups[2].Value; Base = $match.Groups[3].Value; Url = $comment.url }
		}
	}
}

# このheadと向き先の最後の目印がPASSなら、その目印を返す。あとからFINDINGSが出ていれば通さない
function Find-ReusablePass($Comments, [string]$Viewer, [string]$Sha, [string]$Base) {
	$last = @(Get-ReviewMarkers $Comments $Viewer | Where-Object { $_.Sha -eq $Sha -and $_.Base -eq $Base }) | Select-Object -Last 1
	if ($last -and $last.Verdict -eq "pass") { return $last }
	return $null
}

function Get-FindingsCount($Comments, [string]$Viewer) {
	return @(Get-ReviewMarkers $Comments $Viewer | Where-Object { $_.Verdict -eq "findings" }).Count
}

# このheadの codex-review が failure でなければ true。読めないときは false(PASSを使わない側に倒す)
function Test-ReviewStatusAllowsReuse([string]$Sha) {
	Push-Location $RepoRoot
	try {
		$current = gh api "repos/{owner}/{repo}/commits/$Sha/status" --jq '.statuses[] | select(.context == "codex-review") | .state' 2>$null
		if ($LASTEXITCODE -ne 0) { return $false }
		return "$current".Trim() -ne "failure"
	}
	finally {
		Pop-Location
	}
}

# PRのコメントとログイン名を読む。読めなければ $null を返す(目印がないものとして扱う)
function Read-ReviewComments([int]$Number) {
	Push-Location $RepoRoot
	try {
		$viewer = gh api user --jq .login
		if ($LASTEXITCODE -ne 0 -or -not $viewer) { return $null }
		$json = gh pr view $Number --json comments
		if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
		return [pscustomobject]@{ Viewer = "$viewer".Trim(); Comments = ($json | ConvertFrom-Json).comments }
	}
	catch {
		return $null
	}
	finally {
		Pop-Location
	}
}

# レビューしたコミットにステータスを付け、PASSなら自動マージを予約する
function Set-ReviewStatus([string]$Verdict, [string]$Description, [string]$TargetUrl) {
	$state = if ($Verdict -eq "PASS") { "success" } else { "failure" }
	Push-Location $RepoRoot
	try {
		# レビューしたコミット($head)に付ける。レビュー中にpushされていても、新しいheadは未レビューのまま残る
		$statusArgs = @("api", "--silent", "repos/{owner}/{repo}/statuses/$head",
			"-f", "state=$state", "-f", "context=codex-review", "-f", "description=$Description")
		if ($TargetUrl) { $statusArgs += @("-f", "target_url=$TargetUrl") }
		gh @statusArgs
		if ($LASTEXITCODE -ne 0) { throw "コミットステータスの設定に失敗しました。" }
		Write-Output "codex-review: $state ($($head.Substring(0, 7)))"

		if ($Verdict -eq "PASS") {
			$now = gh pr view $Pr --json headRefOid,baseRefName | ConvertFrom-Json
			if ($now.headRefOid -ne $head) {
				Write-Warning "レビュー中にPRのheadが $($now.headRefOid.Substring(0, 7)) に進みました。新しいheadは未レビューのため、自動マージは予約しません。"
			}
			elseif ($now.baseRefName -ne $base) {
				# 保護を確かめたのはレビュー開始時の向き先なので、変わっていたら予約しない
				Write-Warning "レビュー中にPRの向き先が $base から $($now.baseRefName) に変わりました。自動マージは予約しません。"
			}
			else {
				# 必須のチェックがそろっていれば即座に、そうでなければそろった時点でGitHubがマージする
				gh pr merge $Pr --auto --merge
				if ($LASTEXITCODE -ne 0) { throw "自動マージの予約に失敗しました。" }
				if ($needsApproval) {
					Write-Output "自動マージを予約しました。承認待ちです: 人がPRに merge-ok ラベルを付けると、CI・hold・codex-review とそろった時点でマージされます。"
				}
				else {
					Write-Output "自動マージを予約しました(CI・hold・codex-review がそろうとマージされます)。"
				}
			}
		}
	}
	finally {
		Pop-Location
	}
}

# このレビューのrefを消してロックを閉じる。-KeepLock ならロックのファイルは残す(CleanupMerged.ps1 が残りを片付ける目印)
function Remove-ReviewRun([switch]$KeepLock) {
	git -C $RepoRoot update-ref -d "$ref/base"
	git -C $RepoRoot update-ref -d "$ref/head"
	$reviewLock.Dispose()
	# codex の子プロセスが残ってロックを継承していれば消せないので、次の CleanupMerged.ps1 に任せる
	if (-not $KeepLock) { Remove-Item -LiteralPath "$work.lock" -ErrorAction SilentlyContinue }
}

foreach ($tool in "git", "gh", "codex") {
	if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
		throw "$tool が見つかりません。"
	}
}

# Codexの出力(日本語)を文字化けさせずに受け取る
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# gh は呼び出し元のディレクトリで対象リポジトリを決めるため、このリポジトリの中で実行する
Push-Location $RepoRoot
try {
	$info = gh pr view $Pr --json number,title,url,state,baseRefName,headRefOid,mergeCommit | ConvertFrom-Json
	$repoUrl = gh repo view --json url --jq .url
}
finally {
	Pop-Location
}
if (-not $info -or -not $repoUrl) { throw "PR #$Pr の情報を取得できませんでした。" }
$base = $info.baseRefName
$head = $info.headRefOid

# originの設定(fork、single-branch clone など)に左右されないよう、ghが選んだリポジトリから
# baseとPRのheadを、このスクリプト専用のrefに取得先を明示して取得する
# 同じPRを並行してレビューしても衝突しないよう、refとworktreeの名前には実行ごとのIDを含める
$runId = [guid]::NewGuid().ToString('N').Substring(0, 8)
$ref = "refs/codex-review/$Pr-$runId"
$work = Join-Path ([System.IO.Path]::GetTempPath()) "LoopBgmCodexReview-$Pr-$runId"
# refとworktreeを作る前に開く。強制終了で finally が走らなくても、ロックが開けるようになることで終わったと分かる。
# %TEMP% はクローンの間で共有されるので、どのリポジトリのレビューかを書いておく
$repoCommonDir = git -C $RepoRoot rev-parse --path-format=absolute --git-common-dir
$reviewLock = [System.IO.FileStream]::new("$work.lock", [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite,
	[System.IO.FileShare]::None -bor [System.IO.FileShare]::Inheritable)
$ownerBytes = [System.Text.UTF8Encoding]::new($false).GetBytes("$repoCommonDir")
$reviewLock.Write($ownerBytes, 0, $ownerBytes.Length)
$reviewLock.Flush()
# FETCH_HEADは共有されるため、並行して実行したときに書き込みが競合しないよう書き出さない
git -C $RepoRoot fetch --quiet --no-tags --no-write-fetch-head $repoUrl "+refs/heads/${base}:$ref/base" "+refs/pull/$Pr/head:$ref/head"
if ($LASTEXITCODE -ne 0) {
	Remove-ReviewRun
	throw "git fetch に失敗しました。"
}
$baseSha = git -C $RepoRoot rev-parse "$ref/base"
# gh で情報を取得してから push されていても、実際に取得したheadをレビューする
$head = git -C $RepoRoot rev-parse "$ref/head"

# マージ済みのPRは、今のbaseにPR自身の変更が含まれていて差分が空になるため、
# マージコミットの1番目の親(マージ直前のbase)と2番目の親(マージ時点のPRのhead)を比べる
$merged = $info.state -eq "MERGED"
if ($SetStatus -and $info.state -ne "OPEN") {
	Remove-ReviewRun
	throw "-SetStatus はオープンなPRにしか使えません(PR #$Pr は $($info.state))。"
}
if ($SetStatus) {
	# gh pr merge --auto は必須のチェックがないブランチでは即座にマージするため、向き先のブランチ保護が
	# codex-review と hold のチェックを必須にしていることを確かめてから進む(レビューの前に確かめる)。
	# 承認(merge-ok、#160)のチェックは必須にするかを選べる。個人開発で速度を優先するため、今の develop では
	# 必須にしておらず、CI と codex-review がそろえば人の承認なしでマージされる
	Push-Location $RepoRoot
	try {
		$required = @(gh api "repos/{owner}/{repo}/branches/$base/protection/required_status_checks" --jq '.contexts[]' 2>$null)
	}
	finally {
		Pop-Location
	}
	if ($LASTEXITCODE -ne 0 -or "codex-review" -notin $required -or "No hold label" -notin $required) {
		Remove-ReviewRun
		throw "向き先 $base のブランチ保護が codex-review と No hold label を必須にしていないため、-SetStatus(自動マージ)は使えません。"
	}
	$needsApproval = "Merge approved" -in $required

	# 今のheadのPASSがすでにPRにあれば、同じ差分をもう一度Codexに見せない(#195)
	if (-not $ForceReview) {
		$read = Read-ReviewComments $Pr
		$reusable = if ($read) { Find-ReusablePass $read.Comments $read.Viewer $head $base } else { $null }
		if ($reusable -and -not (Test-ReviewStatusAllowsReuse $head)) {
			Write-Output "$($head.Substring(0, 7)) のPASSがありますが、codex-review が failure か読めないので、レビューします。"
			$reusable = $null
		}
		if ($reusable) {
			Remove-ReviewRun
			Write-Output "$($head.Substring(0, 7)) のPASSがPRにあるので、レビューを省略します: $($reusable.Url)(やり直すときは -ForceReview)"
			Write-Output "判定: PASS"
			Set-ReviewStatus "PASS" "Codex review: no findings (PASS comment on this commit)" $reusable.Url
			return
		}
	}
}
$currentSha = $baseSha
if ($merged) {
	$mergeSha = $info.mergeCommit.oid
	$parents = @(git -C $RepoRoot rev-list --parents -n 1 $mergeSha) -split " "
	if ($parents.Count -ne 3) {
		Remove-ReviewRun
		throw "マージコミット $mergeSha の親が2つではありません(squashやrebaseでマージされたPRには未対応です)。"
	}
	$baseSha = $parents[1]
	$head = $parents[2]
}

$log = "$work.log"
git -C $RepoRoot worktree add --quiet --detach $work $head
if ($LASTEXITCODE -ne 0) {
	Remove-ReviewRun
	throw "一時worktreeの作成に失敗しました。"
}

$baseNote = if ($merged) { "マージ直前の $base" } else { "PRの向き先 $base の先端" }
$prompt = @"
このリポジトリは、PR #$Pr「$($info.title)」のheadをチェックアウトしたものです。``git diff $baseSha...HEAD`` (``$baseSha`` は$baseNote)の変更をレビューしてください。
- ファイルは変更せず、ビルドやテストも実行しないこと。
- 文字コード(BOM)や改行コードだけの変更は指摘しなくてよい(BOMが欠けている場合は指摘すること)。
"@
if ($merged) {
	$prompt += @"

- このPRはすでに $base にマージされている。各指摘について、今の $base の先端(``$currentSha``)でもまだ起きるかを ``git show ${currentSha}:<パス>`` などで確かめ、「現在も残っている」か「その後修正済み」かを必ず書くこと。今の規約は ``git show ${currentSha}:CLAUDE.md`` で読める。
"@
}
$prompt += "`n" + @"

- 指摘は日本語で書き、それぞれに重大度(P0〜P3)、ファイル:行、その不具合が起きる具体的な手順や入力を書くこと。推測で書いた指摘はそうと分かるようにすること。
- 変更された行だけでなく、呼び出し元や関連する箇所も読んで、変更が既存の挙動を壊していないかを確かめること。
- リポジトリのCLAUDE.mdの規約も確認すること(特に: C++/C#のファイルはUTF-8 BOM、日本語ヘッダの更新履歴は追記のみ、狭い文字列リテラルに日本語を入れない、async void・OpenProjectViewから呼ばれる経路で例外を投げない、警告を握りつぶさない)。
- 問題がなければ、「問題は見つかりませんでした」という文をそのまま含めて書くこと(この文は機械的に読み取る)。
"@

try {
	Push-Location $work
	try {
		$review = codex review -c 'windows.sandbox="unelevated"' -c "model_reasoning_effort=`"$Effort`"" $prompt 2> $log
		$codexExit = $LASTEXITCODE
	}
	finally {
		Pop-Location
	}

	$logText = if (Test-Path $log) { Get-Content -Raw -Encoding utf8 $log } else { "" }
	$review = ($review -join "`n").Trim()
	if ($codexExit -ne 0 -or -not $review) {
		throw "codex review が失敗しました(終了コード $codexExit)。ログ: $log"
	}
	# ログにはCodexが読んだファイルの内容も残るため、文字列が含まれるだけでは判定せず、
	# 実際にコマンドの実行が拒否されたときのエラー行だけを見る
	if ($logText -match "(?m)^\S+\s+ERROR codex_core::tools::router: .*blocked by policy") {
		throw "Codexがコマンドを実行できず、差分を読めていない可能性があります(blocked by policy)。ログ: $log"
	}

	# 一時worktreeの絶対パスをリポジトリからの相対パスに直す
	foreach ($prefix in ($work + "\"), ($work.Replace("\", "/") + "/")) {
		$review = $review.Replace($prefix, "")
	}
	$model = if ($logText -match "(?m)^model:\s*(\S+)") { $Matches[1] } else { "不明" }
}
finally {
	git -C $RepoRoot worktree remove --force $work 2>$null
	$worktreeRemoved = $LASTEXITCODE -eq 0
	if (-not $worktreeRemoved) { Write-Warning "一時worktreeを削除できませんでした: $work" }
	Remove-ReviewRun -KeepLock:(-not $worktreeRemoved)
}

Remove-Item -ErrorAction SilentlyContinue $log
Write-Output $review

$verdict = Get-ReviewVerdict $review
Write-Output "判定: $verdict"

$commentUrl = $null
if ($Post) {
	$target = if ($merged) {
		"マージ済み。$($head.Substring(0, 7))(マージ直前の ``$base`` の $($baseSha.Substring(0, 7)) との差分)、現在の ``$base`` は $($currentSha.Substring(0, 7))"
	}
	else {
		"$($head.Substring(0, 7))(``$base`` の $($baseSha.Substring(0, 7)) との差分)"
	}
	# マージ済みのPRと判定できなかったレビューには目印を付けない
	$marker = if (-not $merged -and $verdict -in "PASS", "FINDINGS") { "`n" + (Get-ReviewMarker $verdict $head $base) } else { "" }
	$body = @"
## Codex レビュー

対象: $target / モデル: $model / 推論: $Effort

$review

---
``CodexReview.ps1`` による自動レビューです。ビルドやテストは行っていません。指摘は、修正するか、修正しない理由を返信してください。$marker
"@
	$bodyFile = [System.IO.Path]::GetTempFileName()
	Push-Location $RepoRoot
	try {
		[System.IO.File]::WriteAllText($bodyFile, $body, [System.Text.UTF8Encoding]::new($false))
		$commentUrl = gh pr comment $Pr --body-file $bodyFile
		if ($LASTEXITCODE -ne 0) { throw "PRへのコメントに失敗しました。" }
		Write-Output $commentUrl
	}
	finally {
		Pop-Location
		Remove-Item -ErrorAction SilentlyContinue $bodyFile
	}

	# コメントは投稿済みなので、回数を読めなくても失敗にしない
	$read = Read-ReviewComments $Pr
	if ($read) {
		$findingsCount = Get-FindingsCount $read.Comments $read.Viewer
		Write-Output "このPRのFINDINGSの回数: $findingsCount"
		# PASS したなら収束しているので、相談は要らない
		if ($verdict -ne "PASS" -and $findingsCount -gt $FindingsConsultLimit) {
			Write-Output "FINDINGSが $FindingsConsultLimit 回を超えました。直し続けず、コーディネーターに ask で相談してください(方式の問題を疑う。ship-pr スキルの「指摘が収束しないとき」)。"
		}
	}
	else {
		Write-Warning "PRのコメントを読めず、FINDINGSの回数を数えられませんでした。"
	}
}

if ($SetStatus) {
	$description = switch ($verdict) {
		"PASS" { "Codex review: no findings ($model, $Effort)" }
		"FINDINGS" { "Codex review: findings to address ($model, $Effort)" }
		default { "Codex review: could not confirm the review completed" }
	}
	Set-ReviewStatus $verdict $description $commentUrl
}
