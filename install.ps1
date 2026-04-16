param(
    [string]$PythonVersion = "3.12",
    [string]$TextModel = "gemma4:e4b",
    [string]$BaseUrl = "http://127.0.0.1:11434/v1"
)

$ErrorActionPreference = "Stop"

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Require-Command($command, $hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command 未安装。$hint"
    }
}

Write-Step "检查运行环境"
Require-Command "python" "请先安装 Python 3.12，并确保 python 已加入 PATH。"
Require-Command "uv" "请先安装 uv：https://docs.astral.sh/uv/"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

Write-Step "创建运行目录"
New-Item -ItemType Directory -Force -Path ".deps", "data", "data\papers", "data\rules", "data\exports" | Out-Null

Write-Step "安装 Python 依赖到 .deps"
uv run --python $PythonVersion python -m pip install -r requirements.txt --target .deps

Write-Step "写入 Ollama 默认设置"
$settings = @{
    llm = @{
        provider = "ollama"
        base_url = $BaseUrl
        api_key = "ollama"
        text_model = $TextModel
        vision_model = ""
        temperature = 0.2
        max_tokens = 4096
        vision_max_tokens = 1024
        image_analysis_limit = 8
    }
    export = @{
        include_basic_info = $true
        include_summary = $true
        include_dimension_scores = $true
        include_chapter_reviews = $true
        include_issue_list = $true
        include_evidence = $true
        include_polish_suggestions = $true
        include_rule_hits = $true
        include_innovation = $true
    }
}

$settings | ConvertTo-Json -Depth 6 | Set-Content -Path "data\settings.json" -Encoding UTF8

Write-Step "安装完成"
Write-Host "下一步请手动执行：" -ForegroundColor Green
Write-Host "  ollama pull $TextModel"
Write-Host ""
Write-Host "完成后可双击 start.bat，或在 PowerShell 中执行：" -ForegroundColor Green
Write-Host "  .\start.bat"
