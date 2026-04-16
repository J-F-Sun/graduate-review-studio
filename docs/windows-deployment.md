# Windows 11 部署说明

## 适用场景

本文档适用于将当前项目以“源码包 + 本地 Ollama 模型”的方式部署到 Windows 11。

当前推荐方案：

- 项目源码包
- `install.ps1`
- `start.bat`
- 用户手动执行 `ollama pull gemma4:e4b`

## 前置要求

目标机器请先安装：

1. Python 3.12
2. `uv`
3. Ollama for Windows

建议安装完成后在 PowerShell 中确认：

```powershell
python --version
uv --version
ollama --version
```

## 部署步骤

### 1. 解压源码包

将压缩包解压到任意目录，例如：

```text
D:\graduate-review-studio
```

### 2. 执行安装脚本

在 PowerShell 中进入项目目录后执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

脚本会完成：

- 创建 `.deps`
- 安装 Python 依赖
- 初始化 `data/settings.json`
- 将默认 LLM 配置写成 Ollama + `gemma4:e4b`

### 3. 安装本地模型

首次部署时，用户需要手动执行：

```powershell
ollama pull gemma4:e4b
```

### 4. 启动项目

可直接双击：

```text
start.bat
```

也可以在终端中运行：

```powershell
.\start.bat
```

启动成功后访问：

```text
http://127.0.0.1:8000
```

## 默认模型配置

安装脚本默认写入：

- `provider`: `ollama`
- `base_url`: `http://127.0.0.1:11434/v1`
- `api_key`: `ollama`
- `text_model`: `gemma4:e4b`
- `vision_model`: 空

这意味着：

- 文本审稿使用本地 Ollama
- 图片理解默认关闭
- 如果后续换成支持视觉的本地模型，可在页面设置中补填 `vision_model`

## 常见问题

### 1. `uv` 未找到

请先安装 `uv`，然后重新打开 PowerShell。

### 2. 端口被占用

如果启动时报 `Address already in use`，说明 `8000` 端口已被其他进程占用。

可先关闭旧进程，或改为：

```powershell
set PYTHONPATH=.deps
uv run --python 3.12 python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

### 3. Ollama 已安装但模型不存在

重新执行：

```powershell
ollama pull gemma4:e4b
```

### 4. 想改默认模型

可以直接修改：

```text
data/settings.json
```

或在页面“设置”中改。
