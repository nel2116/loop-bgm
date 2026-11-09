<#
.SYNOPSIS
	開発環境を用意する: .venv を作り、loop-bgm を開発用の依存つきで入れる。

.EXAMPLE
	./setup.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
if (-not (Test-Path $venvPython)) {
	# python3 は Windows Store のスタブのことがあるので使わない
	python -m venv .venv
	if ($LASTEXITCODE -ne 0) { throw "python -m venv が失敗しました。Python 3.12 以上を入れてください" }
}
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "pip install が失敗しました" }
& $venvPython -m bgm status
Write-Host "準備できました。音源は .venv/Scripts/python -m bgm fetch で取得します。"
