<#
.SYNOPSIS
    PrePr の検査選択とスタンプを、一時リポジトリと偽の検査で確認する。
#>
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/..").Path
$realPwsh = (Get-Command pwsh).Source
$root = Join-Path ([IO.Path]::GetTempPath()) ("loopbgm_prepr_" + [guid]::NewGuid().ToString('N'))
$savedPath = $env:PATH
try {
    New-Item -ItemType Directory -Path "$root/bin", "$root/.venv/Scripts", "$root/Tests" | Out-Null
    Copy-Item "$repo/PrePr.ps1" "$root/PrePr.ps1"
    New-Item -ItemType File -Path "$root/.venv/Scripts/python.exe", "$root/Tests/WorkerTools.Tests.ps1" | Out-Null
    $env:LOOPBGM_PREPR_TEST_ROOT = $root
    Set-Content "$root/bin/git.ps1" -Value @'
switch ($args[0]) {
    'status' { if ($env:LOOPBGM_PREPR_TEST_DIRTY -eq '1') { ' M tracked.py' } }
    'fetch' { }
    'rev-parse' {
        if ($args -contains '--verify') { exit 0 }
        elseif ($args -contains '--git-path') { 'stamp' }
        else { '0123456789012345678901234567890123456789' }
    }
    'merge-base' { 'base' }
    'diff' { Get-Content "$env:LOOPBGM_PREPR_TEST_ROOT/files" }
    default { throw "未定義の git 呼び出し: $args" }
}
exit 0
'@
    Set-Content "$root/bin/pwsh.ps1" -Value @'
$step = $args[-1]
Add-Content "$env:LOOPBGM_PREPR_TEST_ROOT/steps" $step
if ($env:LOOPBGM_PREPR_TEST_FAIL -and $step.Contains($env:LOOPBGM_PREPR_TEST_FAIL)) {
    '検査の失敗'; exit 7
}
exit 0
'@
    $copy = [IO.File]::ReadAllText("$root/PrePr.ps1").Replace('& pwsh -NoProfile -Command $step', "& '$root/bin/pwsh.ps1' -NoProfile -Command `$step")
    [IO.File]::WriteAllText("$root/PrePr.ps1", $copy, [Text.UTF8Encoding]::new($true))
    $env:PATH = "$root/bin;$savedPath"
    foreach ($name in 'git', 'pwsh') {
        if ((Get-Command $name).Source -notlike (Join-Path $root 'bin*')) { throw "偽の $name が解決されません" }
    }
    function Run([string[]]$files, [bool]$dirty = $false, [string]$fail = '') {
        Set-Content "$root/files" $files
        Remove-Item "$root/steps" -ErrorAction SilentlyContinue
        $env:LOOPBGM_PREPR_TEST_DIRTY = [int]$dirty
        $env:LOOPBGM_PREPR_TEST_FAIL = $fail
        $output = & $realPwsh -NoProfile -File "$root/PrePr.ps1" 2>&1 | Out-String
        $code = $LASTEXITCODE
        $steps = @(if (Test-Path "$root/steps") { Get-Content "$root/steps" })
        [pscustomobject]@{ Code = $code; Output = $output; Steps = $steps }
    }
    function Check([bool]$condition, [string]$message) {
        if (-not $condition) { throw $message }
        Write-Host "ok: $message"
    }
    $r = Run @('docs/example.md')
    Check ($r.Code -eq 0 -and $r.Steps.Count -eq 2) '文書変更は規約と ruff を実行する'
    Check ((Get-Content "$root/stamp" -Raw).Trim() -eq '0123456789012345678901234567890123456789') '成功時に HEAD のスタンプを書く'
    foreach ($file in 'bgm/theory.py', 'pyproject.toml') {
        $r = Run @($file)
        Check ($r.Code -eq 0 -and $r.Steps.Count -eq 3 -and $r.Steps[-1] -match 'pytest') "$file の変更は pytest を追加する"
    }
    $r = Run @('StartWorker.ps1', 'WorkerStatus.ps1', 'Tests/WorkerTools.Tests.ps1')
    Check ($r.Code -eq 0 -and $r.Steps.Count -eq 3 -and $r.Steps[-1] -match 'WorkerTools') '共通のテストを重複実行しない'
    $r = Run @('bgm/theory.py') $false 'ruff'
    Check ($r.Code -ne 0 -and $r.Steps.Count -eq 2 -and $r.Output -match '検査の失敗') '失敗で停止し、失敗内容を表示する'
    Check (-not (Test-Path "$root/stamp")) '検査失敗で古いスタンプを残さない'
    $r = Run @('bgm/theory.py') $true
    Check ($r.Code -ne 0 -and $r.Steps.Count -eq 0) '未コミットの変更は検査前に拒否する'
}
finally {
    $env:PATH = $savedPath
    foreach ($name in 'ROOT', 'DIRTY', 'FAIL') {
        Remove-Item "Env:LOOPBGM_PREPR_TEST_$name" -ErrorAction SilentlyContinue
    }
    # 作成した一時ディレクトリの絶対パスを確認してから削除する。
    $target = [IO.Path]::GetFullPath($root)
    if ((Split-Path $target -Parent) -eq ([IO.Path]::GetTempPath()).TrimEnd('\') -and
        (Split-Path $target -Leaf) -like 'loopbgm_prepr_*') {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
