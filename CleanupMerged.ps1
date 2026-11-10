<#
.SYNOPSIS
	マージ済みのPRのworktreeとローカルブランチを片付け、ルートのdevelopを最新にするスクリプト。

.DESCRIPTION
	PRがマージされたあとの手元の片付けをまとめて行う。リモートのブランチはGitHubの設定
	(delete_branch_on_merge)でマージ時に消え、Issueは .github/workflows/pr-automation.yml が閉じるので、
	ここでは手元の状態だけを扱う。

	消すのは、次をすべて満たすものだけ。満たさないものは理由を表示して残す。
	- ブランチに対応するPRがマージ済み(gh pr list --state merged --head <ブランチ>)
	- ブランチの先端が origin/develop に含まれている(マージ後に足したコミットがない)
	- worktreeに未コミットの変更や追跡されていないファイルがない(無視されたビルド成果物は除く)
	- worktreeでOrcaのターミナルが開いていない(orca terminal list。#133)
	- worktreeに、解放されていないOrcaのworkerがいない(直接移譲は新旧双方の終了を証明した場合だけ例外)
	  (Runごとの orca orchestration worker-list。structured の形式のworkerは terminal list に出ないため。#166)
	起点にしただけでまだコミットのない作業中のworktreeは、マージ済みのPRがないので消さない。
	orca worktree rm はそのworktreeのターミナルも閉じるので、PRのマージ後に worker_done を送る前の
	Orcaのworkerを止めてしまう。workerのworktreeは worker_done と worker-release のあとの実行で消える。
	Orcaが入っているのにターミナルやworkerを確かめられないとき(Orcaが起動していないなど)は、消さずに残す。

	Orcaが管理するworktreeは orca worktree rm で消す(Orcaの記録とブランチも一緒に消える)。
	それ以外、またはOrcaで消せなかったときは git worktree remove と git branch -D を使う。
	orca worktree rm はブランチやフォルダを消し終える前に成功を返すことがあるので、worktreeの登録、
	ブランチ、フォルダが消えるまで0.5秒おきに最大15秒待つ。待っても残ったブランチは git branch -D で消す
	(worktreeの登録が残っているときは、使用中の可能性があるので触らない)。
	削除のあとにフォルダが残っていたら(ファイルがロックされているなど)、警告を出し、そのフォルダの下の
	DLLやexeを読み込んでいるプロセスを候補として表示する。プロセスは終了させず、フォルダも消さない。

	CodexReview.ps1 が強制終了で残したもの(一時worktree、refs/codex-review/*、ログ、ロック)は、実行ごとに
	ロックを開いて調べる。開けたら誰も使っていないので消す。共有違反なら実行中なので触らない。
	worktreeもrefもないロックは、ロックに書かれたリポジトリがこのリポジトリのときだけ消す(%TEMP% は共有のため)。
	ロックがないか確かめられないときは、消さずに警告して手のコマンドを出す。

	最後に、ルートのチェックアウトが develop で、追跡しているファイルに変更がなければ
	git pull --ff-only する。

.PARAMETER DryRun
	何を消すか(残すか)を表示するだけで、変更はしない。

.EXAMPLE
	./CleanupMerged.ps1 -DryRun
	片付けの対象を確かめる。

.EXAMPLE
	./CleanupMerged.ps1
	マージ済みのworktreeとブランチを消し、developを最新にする。
#>
[CmdletBinding()]
param(
	[switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

foreach ($tool in "git", "gh") {
	if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
		throw "$tool が見つかりません。"
	}
}
$orca = if ($env:ORCA_CLI_COMMAND) { $env:ORCA_CLI_COMMAND } else { "orca" }
$hasOrca = [bool](Get-Command $orca -ErrorAction SilentlyContinue)
# 指定 CLI を確認できない場合は削除前に止める。別ビルドや git の削除へ切り替えない(#7)
if ($env:ORCA_CLI_COMMAND -and -not $hasOrca) {
	throw "指定された Orca CLI が見つかりません: $orca。worktree を保持します。"
}

# git worktree list の先頭はメインのworktree(ルートのチェックアウト)。
# このスクリプトがworktreeの中から実行されても、ルートを基準にする。
# 最初はルートを知るためにスクリプトのフォルダから読み、以後は消えることのないルートから読む
# (スクリプトのあるworktreeを消したあとに読み直すと、消えたフォルダを -C に渡すことになるため)
$gitBase = $PSScriptRoot
function Get-Worktrees {
	$porcelain = git -C $gitBase worktree list --porcelain
	if ($LASTEXITCODE -ne 0) { throw "git worktree list に失敗しました。" }
	$list = @()
	$current = $null
	foreach ($line in $porcelain) {
		if ($line -match '^worktree (.+)$') {
			$current = [ordered]@{ Path = $Matches[1]; Branch = $null; Prunable = $false }
			$list += $current
		}
		elseif ($line -match '^branch refs/heads/(.+)$') { $current.Branch = $Matches[1] }
		elseif ($line -match '^prunable') { $current.Prunable = $true }
	}
	return $list
}
$worktrees = @(Get-Worktrees)
$root = $worktrees[0].Path
$gitBase = $root

function Invoke-Step([string]$description, [scriptblock]$action) {
	if ($DryRun) {
		Write-Host "  (DryRun) $description"
		return $true
	}
	# コマンドの出力が戻り値に混ざらないよう、画面にだけ出す
	& $action | ForEach-Object { Write-Host "  $_" }
	return ($LASTEXITCODE -eq 0)
}

Push-Location $root
try {
	git fetch --quiet --prune origin
	if ($LASTEXITCODE -ne 0) { throw "git fetch に失敗しました。" }
	if (-not $DryRun) { git worktree prune }

	# マージ済みかどうかはブランチ名でPRを引いて判定する(同じ名前で何度もPRを作ることはない前提)
	$mergedCache = @{}
	function Get-MergedPr([string]$branch) {
		if (-not $mergedCache.ContainsKey($branch)) {
			$pr = gh pr list --state merged --head $branch --limit 1 --json number --jq '.[0].number'
			$mergedCache[$branch] = if ($LASTEXITCODE -eq 0 -and $pr) { [int]$pr } else { $null }
		}
		return $mergedCache[$branch]
	}

	function Test-Removable([string]$branch, [string]$path) {
		if ($branch -in "develop", "main") { return "保護するブランチ" }
		$pr = Get-MergedPr $branch
		if (-not $pr) { return "マージ済みのPRがない" }
		git merge-base --is-ancestor "refs/heads/$branch" origin/develop
		if ($LASTEXITCODE -ne 0) { return "PR #$pr のマージ後に足したコミットがある" }
		if ($path) {
			# status.showUntrackedFiles などの設定に左右されないよう、追跡されていないファイルの表示を明示する
			$dirty = git -C $path status --porcelain --untracked-files=all
			if ($LASTEXITCODE -ne 0) { return "worktreeの状態を確認できない" }
			if ($dirty) { return "未コミットの変更か追跡されていないファイルがある" }
			$terminals = Get-OrcaTerminalReason $path
			if ($terminals) { return $terminals }
			$workers = Get-OrcaWorkerReason $path
			if ($workers) { return $workers }
		}
		return $null
	}

	function Get-NormalizedPath([string]$path) {
		return [IO.Path]::GetFullPath($path.Replace('/', '\')).TrimEnd('\')
	}

	# worktreeでOrcaのターミナルが開いていれば、残す理由を返す(#133)。
	# 確かめられないときも残す(消し損ねても次の実行で消えるが、消しすぎるとworkerを止めてしまう)
	function Get-OrcaTerminalReason([string]$path) {
		if (-not $hasOrca) { return $null }
		$unknown = "Orcaのターミナルを確認できない(Orcaを起動してから実行し直す)"
		$json = & $orca terminal list --limit 100000 --json 2>$null | Out-String
		if ($LASTEXITCODE -ne 0) { return $unknown }
		try { $list = $json | ConvertFrom-Json }
		catch { return $unknown }
		if (-not $list.ok -or $null -eq $list.result.terminals -or $list.result.truncated) { return $unknown }
		$target = Get-NormalizedPath $path
		$open = @($list.result.terminals | Where-Object { $_.worktreePath -and (Get-NormalizedPath $_.worktreePath) -eq $target })
		if ($open.Count) {
			return "Orcaのターミナルが $($open.Count) 個開いている。workerなら worker_done と worker-release のあとに消す"
		}
		return $null
	}

	# orca のページ付きの一覧(nextCursor)を最後まで読み、$property の要素を返す。読めなければ $null
	function Read-OrcaPages([string[]]$arguments, [string]$property) {
		$items = [System.Collections.Generic.List[object]]::new()
		$cursor = $null
		$seen = [System.Collections.Generic.HashSet[string]]::new()
		do {
			$pageArgs = $arguments + @("--json", "--full")
			if ($cursor) { $pageArgs += @("--cursor", $cursor) }
			$json = & $orca @pageArgs 2>$null | Out-String
			if ($LASTEXITCODE -ne 0) { return $null }
			try { $page = $json | ConvertFrom-Json }
			catch { return $null }
			if ($page.ok -isnot [bool] -or -not $page.ok -or $page.result.$property -isnot [array]) { return $null }
			if ($page.result.truncated -and -not $page.result.nextCursor) { return $null }
			$page.result.$property | ForEach-Object { $items.Add($_) }
			$cursor = $page.result.nextCursor
			if ($cursor -and ($cursor -isnot [string] -or -not $seen.Add($cursor))) { return $null }
		} while ($cursor)
		return , $items
	}

	# 新旧の一覧形式を受け付けるが、両方に値がある場合の矛盾は不明として扱う。
	function Get-WorkerWorkspace($worker) {
		$legacy = $worker.workspace
		$current = $worker.projection.workspace.id
		if ($legacy -and $current -and $legacy -ne $current) { return $null }
		$value = if ($current) { $current } else { $legacy }
		if ($value -isnot [string] -or $value -notmatch '^.+?::([A-Za-z]:[/\\].+|/.*)$') { return $null }
		return $value
	}

	function Read-WorkerShow([string]$id) {
		$json = & $orca orchestration worker-show --dispatch $id --json --full 2>$null | Out-String
		if ($LASTEXITCODE -ne 0) { return $null }
		try { $reply = $json | ConvertFrom-Json } catch { return $null }
		if ($reply.ok -isnot [bool] -or -not $reply.ok -or $reply.result.dispatch.id -ne $id) { return $null }
		return $reply.result
	}

	# 直接の追作業に移った資源だけを例外にする。成功状態や所在不明を終了証拠にしない。
	function Test-ExitedTransfer($old, $all) {
		if ($old.resource -or $old.terminalState -or -not $old.dispatchId -or -not $old.runId) { return $false }
		$successors = @($all | Where-Object { $_.resource.originDispatchId -eq $old.dispatchId })
		if ($successors.Count -ne 1) { return $false }
		$new = $successors[0]
		if ($new.dispatchId -eq $old.dispatchId -or $new.terminalState -ne 'released') { return $false }
		if (@($all | Where-Object { $_.dispatchId -eq $old.dispatchId }).Count -ne 1 -or
			@($all | Where-Object { $_.dispatchId -eq $new.dispatchId }).Count -ne 1 -or
			@($all | Where-Object { $_.resource.originDispatchId -eq $new.dispatchId }).Count) { return $false }
		$workspace = Get-WorkerWorkspace $old
		if ($new.runId -ne $old.runId -or (Get-WorkerWorkspace $new) -ne $workspace) { return $false }
		$a = Read-WorkerShow $old.dispatchId
		$b = Read-WorkerShow $new.dispatchId
		if (-not $a -or -not $b -or $a.dispatch.followUpOf -or $b.dispatch.followUpOf -ne $old.dispatchId) { return $false }
		foreach ($show in $a, $b) {
			if ($show.observation.exactWorker -isnot [bool] -or -not $show.observation.exactWorker -or
				$show.observation.status -ne 'exited' -or $show.projection.liveness.verdict -eq 'live' -or
				$show.dispatch.runId -ne $old.runId -or $show.worker.worktreeId -ne $workspace -or
				$show.worker.dispatchId -ne $show.dispatch.id -or -not $show.dispatch.assigneeHandle -or
				-not $show.dispatch.processIncarnation -or $show.worker.agentTerminalHandle -ne $show.dispatch.assigneeHandle -or
				$show.dispatch.hostScope.kind -ne 'local' -or $show.dispatch.hostScope.hostId -ne 'local') { return $false }
		}
		if ($a.dispatch.assigneeHandle -ne $b.dispatch.assigneeHandle -or
			$a.dispatch.processIncarnation -ne $b.dispatch.processIncarnation -or $a.terminalResource) { return $false }
		foreach ($resource in $new.resource, $b.terminalResource) {
			if (-not $resource -or $resource.originDispatchId -ne $old.dispatchId -or
				$resource.ownerDispatchId -ne $new.dispatchId -or $resource.worktreeId -ne $workspace -or
				$resource.terminalHandle -ne $b.dispatch.assigneeHandle -or
				$resource.endpointIncarnation -ne $b.dispatch.processIncarnation -or
				$resource.ownershipState -ne 'released' -or $resource.releaseState -ne 'released') { return $false }
		}
		return $true
	}

	# released でない Orca の worker の worktree のパス。読めなければ $null(#166)
	# structured の形式で起動した worker は terminal list に出ないので、worker-list でも調べる。
	# worker-list は --run を付けないと呼び出したターミナルの Run しか返さないので、Run ごとに読む
	$script:orcaWorkerPaths = $null
	$script:orcaWorkersRead = $false
	function Get-OrcaWorkerPaths {
		# 空のリストが $null にならないよう、, を付けて返す
		if ($script:orcaWorkersRead) {
			if ($null -eq $script:orcaWorkerPaths) { return $null }
			return , $script:orcaWorkerPaths
		}
		$script:orcaWorkersRead = $true
		$runs = Read-OrcaPages @("orchestration", "run-list") "runs"
		if ($null -eq $runs) { return $null }
		$paths = [System.Collections.Generic.List[string]]::new()
		$all = [System.Collections.Generic.List[object]]::new()
		foreach ($run in $runs) {
			if (-not $run.id -or $run.id -isnot [string]) { return $null }
			$workers = Read-OrcaPages @("orchestration", "worker-list", "--run", $run.id) "workers"
			if ($null -eq $workers) { return $null }
			foreach ($worker in $workers) {
				if (-not (Get-WorkerWorkspace $worker) -or -not $worker.dispatchId) { return $null }
				if ($worker.runId -and $worker.runId -ne $run.id) { return $null }
				$all.Add($worker)
			}
		}
		foreach ($worker in $all) {
			if ($worker.terminalState -eq 'released' -or (Test-ExitedTransfer $worker $all)) { continue }
			$paths.Add((Get-NormalizedPath ((Get-WorkerWorkspace $worker) -replace '^.*?::', '')))
		}
		$script:orcaWorkerPaths = $paths
		return , $paths
	}

	# worktreeに released でない Orca の worker がいれば、残す理由を返す(#166)。確かめられないときも残す
	function Get-OrcaWorkerReason([string]$path) {
		if (-not $hasOrca) { return $null }
		$paths = Get-OrcaWorkerPaths
		if ($null -eq $paths) { return "Orcaのworkerを確認できない(Orcaを起動してから実行し直す)" }
		if ((Get-NormalizedPath $path) -in $paths) {
			return "Orcaのworkerがまだ解放されていない。worker_done と worker-release のあとに消す"
		}
		return $null
	}

	function Get-RemovalState([string]$path, [string]$branch) {
		git show-ref --verify --quiet "refs/heads/$branch"
		$branchExists = ($LASTEXITCODE -eq 0)
		return [ordered]@{
			Registered   = $path -in @(Get-Worktrees | ForEach-Object { $_.Path })
			BranchExists = $branchExists
			FolderExists = Test-Path -LiteralPath $path
		}
	}

	# orca worktree rm はブランチやフォルダを消し終える前に成功を返すことがある(#104)ので、
	# worktreeの登録、ブランチ、フォルダがすべて消えるまで待つ。上限を過ぎたら、そのときの状態を返す
	function Wait-WorktreeRemoved([string]$path, [string]$branch) {
		$deadline = [DateTime]::UtcNow.AddSeconds(15)
		while ($true) {
			$state = Get-RemovalState $path $branch
			if (-not ($state.Registered -or $state.BranchExists -or $state.FolderExists)) { return $state }
			if ([DateTime]::UtcNow -ge $deadline) { return $state }
			Start-Sleep -Milliseconds 500
		}
	}

	# 削除のあとにフォルダが残っていたら、警告と、ロックしている可能性のあるプロセスを表示する。
	# プロセスの終了やフォルダの削除は利用者に任せる
	function Write-LeftoverFolder([string]$path) {
		if ($DryRun -or -not (Test-Path -LiteralPath $path)) { return }
		$files = @(Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue).Count
		Write-Warning "worktreeのフォルダが残っています: $path(ファイル $files 個)"
		$prefix = [IO.Path]::GetFullPath($path).TrimEnd('\') + '\'
		$unreadable = 0
		$lockers = foreach ($proc in Get-Process) {
			# 権限のないプロセスは Modules が空になるか例外になる
			try { $modules = $proc.Modules } catch { $modules = $null }
			if (-not $modules) { $unreadable++; continue }
			if ($modules | Where-Object { $_.FileName -and $_.FileName.Replace('/', '\').StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) }) {
				"$($proc.ProcessName) (PID $($proc.Id))"
			}
		}
		if ($lockers) {
			Write-Warning "  このフォルダの下のDLLやexeを読み込んでいるプロセス: $($lockers -join ', ')"
		}
		else {
			Write-Warning "  このフォルダの下のDLLやexeを読み込んでいるプロセスは見つかりませんでした。"
		}
		Write-Warning "  (調べられなかったプロセス: $unreadable 個。32bitのプロセスのDLLと、DLL以外の開いているファイルは調べられません)"
		Write-Warning "  プロセスを終了してから、フォルダを手で消してください。"
	}

	# CodexReview.ps1 の一時worktreeなら、実行ごとのID(<PR番号>-<ID>)を返す
	function Get-ReviewRunKey($wt) {
		if (-not $wt.Branch -and (Split-Path -Leaf $wt.Path) -match '^LoopBgmCodexReview-(\d+-[0-9a-f]{8})$') { return $Matches[1] }
		return $null
	}

	# 開いたロックか、開けない理由("busy"、"missing"、それ以外は説明)を返す
	function Open-ReviewLock([string]$path) {
		if (-not (Test-Path -LiteralPath $path)) { return "missing" }
		try { return [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
		catch {
			$failure = $_.Exception.GetBaseException()
			# ERROR_SHARING_VIOLATION(32)、ERROR_LOCK_VIOLATION(33)
			if (($failure.HResult -band 0xFFFF) -in 32, 33) { return "busy" }
			return $failure.Message
		}
	}

	# ロックに書かれた、レビューを実行したリポジトリ(git の共通フォルダ)を返す
	function Read-ReviewLockOwner([IO.FileStream]$lock) {
		# 最後の引数でロックを閉じないようにする
		$reader = [IO.StreamReader]::new($lock, [Text.Encoding]::UTF8, $true, 1024, $true)
		try { return $reader.ReadToEnd().Trim() }
		finally { $reader.Dispose() }
	}

	Write-Output "== worktree"
	$removedBranches = @()
	foreach ($wt in $worktrees | Select-Object -Skip 1) {
		if ($wt.Prunable) { continue }
		if (-not $wt.Branch) {
			# CodexReview.ps1 の一時worktreeは下の「== review worktree」で扱う
			if (Get-ReviewRunKey $wt) { continue }
			Write-Output "残す: $($wt.Path)(detached HEAD)"
			continue
		}
		$reason = Test-Removable $wt.Branch $wt.Path
		if ($reason) {
			Write-Output "残す: $($wt.Path) [$($wt.Branch)]($reason)"
			continue
		}

		Write-Output "削除: $($wt.Path) [$($wt.Branch)](PR #$(Get-MergedPr $wt.Branch) はマージ済み)"
		$done = $false
		if ($hasOrca -and -not $DryRun) {
			$result = & $orca worktree rm --worktree "path:$($wt.Path)" --json 2>$null | Out-String
			$done = ($LASTEXITCODE -eq 0) -and ($result -match '"ok":\s*true')
			if (-not $done) { Write-Output "  Orcaでは消せなかったため、gitで消します。" }
		}
		if ($done) {
			$state = Wait-WorktreeRemoved $wt.Path $wt.Branch
			if ($state.Registered) {
				# 使用中の可能性があるので、ブランチには触らない
				Write-Warning "Orcaの削除が終わりませんでした(worktreeの登録が残っています): $($wt.Path)"
				continue
			}
			if ($state.BranchExists) {
				$branch = $wt.Branch
				Write-Output "  Orcaがブランチを消し終えなかったため、gitで消します。"
				if (-not (Invoke-Step "git branch -D $branch" { git branch -D $branch | Out-Null })) {
					# 消している間にOrcaが消し終えたのなら問題ない
					git show-ref --verify --quiet "refs/heads/$branch"
					if ($LASTEXITCODE -eq 0) { Write-Warning "ブランチを削除できませんでした: $branch" }
				}
			}
		}
		else {
			$path = $wt.Path
			if (-not (Invoke-Step "git worktree remove $path" { git worktree remove $path })) {
				Write-Warning "worktreeを削除できませんでした: $path"
				Write-LeftoverFolder $path
				continue
			}
		}
		Write-LeftoverFolder $wt.Path
		$removedBranches += $wt.Branch
	}

	Write-Output "== review worktree"
	# CodexReview.ps1 の実行ごとに、登録されたworktree、ref、%TEMP% のロックを集める。
	# ロックだけのものは、refを作る前に止まったときと、子プロセスが残ってロックを消せなかったときに残る
	$reviewTemp = [IO.Path]::GetTempPath()
	$repoCommonDir = git rev-parse --path-format=absolute --git-common-dir
	$reviewRuns = [ordered]@{}
	function Get-ReviewRun([string]$key) {
		if (-not $reviewRuns.Contains($key)) { $reviewRuns[$key] = [pscustomobject]@{ Key = $key; Worktree = $null; Refs = @() } }
		return $reviewRuns[$key]
	}
	foreach ($wt in Get-Worktrees) {
		$key = Get-ReviewRunKey $wt
		if ($key) { (Get-ReviewRun $key).Worktree = $wt.Path }
	}
	foreach ($name in git for-each-ref --format='%(refname)' refs/codex-review) {
		$run = Get-ReviewRun (($name -replace '^refs/codex-review/', '') -replace '/[^/]+$', '')
		$run.Refs += $name
	}
	foreach ($file in Get-ChildItem -LiteralPath $reviewTemp -Filter 'LoopBgmCodexReview-*.lock' -File -ErrorAction SilentlyContinue) {
		if ($file.BaseName -match '^LoopBgmCodexReview-(\d+-[0-9a-f]{8})$') { Get-ReviewRun $Matches[1] | Out-Null }
	}
	foreach ($run in $reviewRuns.Values) {
		$folder = if ($run.Worktree) { Get-NormalizedPath $run.Worktree } else { Join-Path $reviewTemp "LoopBgmCodexReview-$($run.Key)" }
		$lock = Open-ReviewLock "$folder.lock"
		if ($lock -eq "busy") {
			Write-Output "残す: $folder(レビューの実行中)"
			continue
		}
		if ($lock -is [string]) {
			$why = if ($lock -eq "missing") { "ロックがありません" } else { "ロックを確かめられません: $lock" }
			Write-Warning "レビューの残りを消しません($why): $($run.Key)"
			Write-Warning "  使われていないことを確かめてから、手で消してください:"
			if ($run.Worktree) { Write-Warning "  git worktree remove --force `"$($run.Worktree)`"" }
			foreach ($name in $run.Refs) { Write-Warning "  git update-ref -d $name" }
			continue
		}
		# worktreeもrefもこのリポジトリになければ、別のクローンのレビューかもしれない。
		# 消すと、持ち主のクローンでそのworktreeとrefを片付けられなくなる
		if (-not $run.Worktree -and -not $run.Refs) {
			$owner = Read-ReviewLockOwner $lock
			if ($owner -ne $repoCommonDir) {
				$lock.Dispose()
				Write-Output "残す: $folder(このリポジトリのレビューではない: $owner)"
				continue
			}
		}
		Write-Output "削除: $folder(レビューは終わっている)"
		$done = $true
		try {
			# ロックを開いたまま消す
			if ($run.Worktree) {
				$path = $run.Worktree
				if (-not (Invoke-Step "git worktree remove --force $path" { git worktree remove --force $path })) {
					Write-Warning "一時worktreeを削除できませんでした: $path"
					$done = $false
				}
			}
			# git worktree remove はフォルダを消せなくても登録を消すので、登録のないフォルダも残っていることがある
			if (-not $DryRun -and (Test-Path -LiteralPath $folder)) {
				Remove-Item -LiteralPath $folder -Recurse -Force -ErrorAction SilentlyContinue
				if (Test-Path -LiteralPath $folder) {
					Write-LeftoverFolder $folder
					$done = $false
				}
			}
			foreach ($name in $run.Refs) {
				if (-not (Invoke-Step "git update-ref -d $name" { git update-ref -d $name })) {
					Write-Warning "refを削除できませんでした: $name"
					$done = $false
				}
			}
		}
		finally {
			$lock.Dispose()
		}
		# 残りがあるときはロックも残し、次の実行でやり直す
		if ($done -and -not $DryRun) {
			Remove-Item -LiteralPath "$folder.log", "$folder.lock" -ErrorAction SilentlyContinue
		}
	}

	Write-Output "== ローカルブランチ"
	# DryRunでは何も消していないので、消すはずのworktreeのブランチも対象として表示する。
	# 実際に消したときは、Orcaが消したブランチや登録の残ったworktreeを正しく扱えるよう、今の状態を読み直す
	$remaining = if ($DryRun) { $worktrees | Where-Object { $_.Branch -notin $removedBranches } } else { Get-Worktrees }
	$checkedOut = @($remaining | Where-Object { -not $_.Prunable } | ForEach-Object { $_.Branch }) | Where-Object { $_ }
	foreach ($branch in git for-each-ref --format='%(refname:short)' refs/heads) {
		if ($branch -in $checkedOut) { continue }
		# Orcaがworktreeと一緒に消したブランチは、ここではもう存在しない
		git show-ref --verify --quiet "refs/heads/$branch"
		if ($LASTEXITCODE -ne 0) { continue }
		$reason = Test-Removable $branch $null
		if ($reason) {
			if ($reason -ne "保護するブランチ") { Write-Output "残す: $branch($reason)" }
			continue
		}
		Write-Output "削除: $branch(PR #$(Get-MergedPr $branch) はマージ済み)"
		if (-not (Invoke-Step "git branch -D $branch" { git branch -D $branch | Out-Null })) {
			Write-Warning "ブランチを削除できませんでした: $branch"
		}
	}

	Write-Output "== ルートのチェックアウト"
	$rootBranch = git rev-parse --abbrev-ref HEAD
	$rootDirty = git status --porcelain --untracked-files=no
	if ($rootBranch -ne "develop") {
		Write-Output "pullしない: ルートが develop ではない($rootBranch)"
	}
	elseif ($rootDirty) {
		Write-Output "pullしない: 追跡しているファイルに変更がある"
	}
	else {
		if (-not (Invoke-Step "git pull --ff-only" { git pull --quiet --ff-only })) {
			Write-Warning "git pull --ff-only に失敗しました(developに手元だけのコミットがある可能性があります)。"
		}
		elseif (-not $DryRun) {
			Write-Output "develop: $(git log --oneline -1)"
		}
	}
}
finally {
	Pop-Location
}
