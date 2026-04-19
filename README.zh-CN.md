# Zotero → Markdown 自动转换管线

**把你整个 Zotero PDF 文献库转成可搜索的 Markdown 语料库，让 AI 代理来读。**

English version: [README.md](README.md)

```text
 ┌──────────────┐
 │ zotero.sqlite│── collection 层级 ───┐
 └──────────────┘                      ▼
                                ┌──────────────┐     ┌──────────────┐
 ┌──────────────┐   PDF 文件   │ Markdown +   │     │ AI 代理      │
 │ PDF 目录     │─────────────▶│ frontmatter  │────▶│ 检索、总结   │
 │ (Google Drive│   Marker    │ + symlink    │     │ 交叉引用     │
 │  或本地)     │              │   镜像       │     └──────────────┘
 └──────────────┘              └──────────────┘
```

**核心功能：**
- 通过 [Marker](https://github.com/datalab-to/marker) 批量 PDF→Markdown 转换
- 只读读取 Zotero 的 `zotero.sqlite`，获取 collection 层级
- 创建 symlink 镜像，让 Markdown 库的文件夹结构与 Zotero 一致
- 在 YAML frontmatter 中写入 `zotero_collections` 标签
- 自动监听新增 PDF 并同步 collection 变更
- 配合 [zotero-attanger](https://github.com/HenryYu-1022/zotero-attanger) 实现 Google Drive 多设备 PDF 同步

---

## 运行前准备

| 依赖 | 说明 |
|---|---|
| Python ≥ 3.10 | [python.org](https://www.python.org/downloads/) |
| PyTorch | [pytorch.org](https://pytorch.org/get-started/locally/) — CUDA / MPS / CPU |
| Marker | `pip install marker-pdf` |
| 项目依赖 | `pip install -r requirements.txt` |

> **硬件：** 强烈建议有 GPU（NVIDIA CUDA 或 Apple MPS）。CPU 也能跑但非常慢。

---

## 一步步上手

### 第 1 步 — 创建配置文件

```bash
cp paper_to_markdown/settings.example.json paper_to_markdown/settings.json
```

编辑 `paper_to_markdown/settings.json`，关键字段：

```jsonc
{
  "input_root":    "/你的/PDF/文件夹路径",            // PDF 所在目录
  "output_root":   "/你的/输出/文件夹路径",           // Markdown 输出目录
  "marker_cli":    "marker_single",                  // 或绝对路径
  "hf_home":       "/你的/.cache/huggingface",
  "torch_device":  "cuda",                           // cuda / mps / cpu
  "zotero_db_path": "/你的/Zotero/zotero.sqlite"     // 可选，启用 collection 镜像
}
```

完整配置项见 [配置项说明](#配置项说明)。

### 第 2 步 — 批量转换全部 PDF

```bash
cd paper_to_markdown
python3 convert.py
```

### 第 3 步 —（可选）启动文件监听

监听 `input_root`，新增/修改 PDF 自动转换：

```bash
cd paper_to_markdown
python3 watch.py
```

### 第 4 步 —（可选）同步 Zotero 集合层级

把 Zotero 的 collection 层级镜像到 Markdown 库：

```bash
cd paper_to_markdown

# 单次同步
python3 sync_collections.py --once

# 或后台守护（默认每 60 秒轮询）
python3 sync_collections.py
```

### 第 5 步 — 交给 AI

用 Codex、Claude Code 或任何 AI 编程代理打开 `output_root/markdown/` 目录。跨你整个文献库提问。

---

## 输出结构

```text
output_root/
  markdown/           ← 你的 Markdown 库（用 AI / Obsidian 打开）
    Paper1/
      Paper1.md       ← 带 YAML frontmatter 的转换结果
    Collection1/
      Paper2/         ← Zotero collection 的 symlink 镜像
  state/
    manifest.json     ← 转换状态追踪
  logs/
    app.log
    failed_pdfs.txt
```

每个 `.md` 文件包含 YAML frontmatter：

```yaml
---
source_pdf: /path/to/Paper1.pdf
source_filename: Paper1.pdf
zotero_collections:    # 仅配置 zotero_db_path 后出现
  - 我的文库/硕士论文/光热催化
  - 我的文库/硕士论文/高熵课题
---
```

---

## 常用命令速查

| 你想做什么 | 命令 |
|---|---|
| 一次性转换所有 PDF | `cd paper_to_markdown && python3 convert.py` |
| 只转一个 PDF | `python3 convert.py --path "/path/to/Paper.pdf"` |
| 强制全部重转 | `python3 convert.py --force` |
| 只测前 N 个 | `python3 convert.py --limit 5` |
| 清理孤儿 Markdown | `python3 convert.py --cleanup` |
| 监听新 PDF | `cd paper_to_markdown && python3 watch.py` |
| 同步 Zotero collection（单次） | `cd paper_to_markdown && python3 sync_collections.py --once` |
| 同步 Zotero collection（守护） | `cd paper_to_markdown && python3 sync_collections.py` |
| 查看转换进度 | `python3 monitor.py` |

---

## 开机自启动

**macOS：**
```bash
zsh ./watch_autostart.sh install   # 安装
zsh ./watch_autostart.sh status    # 检查状态
zsh ./watch_autostart.sh remove    # 卸载
```

**Windows（管理员运行）：**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\watch_autostart.ps1
```

> 自启动只覆盖 PDF 监听器。如需持续同步 Zotero collection，请单独运行 `sync_collections.py`。

---

## 配置项说明

配置文件：`paper_to_markdown/settings.json`

| 键名 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `input_root` | ✅ | — | PDF 源目录 |
| `output_root` | ✅ | — | Markdown、日志、状态的输出目录 |
| `marker_cli` | ✅ | — | Marker 命令名或路径（如 `marker_single`） |
| `hf_home` | ✅ | — | HuggingFace 缓存目录 |
| `torch_device` | | `cuda` | `cuda` / `mps` / `cpu` |
| `force_ocr` | | `false` | 是否强制 OCR |
| `zotero_db_path` | | — | `zotero.sqlite` 路径；填写后启用 collection 镜像 |
| `collection_mirror_mode` | | `symlink` | `symlink` 或 `copy` |
| `zotero_sync_interval_seconds` | | `60` | collection 同步轮询间隔 |
| `watch_initial_scan` | | `true` | 监听器启动时是否先处理已有 PDF |
| `python_path` | | — | Python 绝对路径（后台自启动用） |
| `log_level` | | `INFO` | 日志级别 |

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `paper_to_markdown/convert.py` | 手动批量转换 CLI |
| `paper_to_markdown/watch.py` | 文件监听守护进程 |
| `paper_to_markdown/sync_collections.py` | Zotero collection 同步守护进程 |
| `paper_to_markdown/settings.json` | 你的本地配置（从 `.example.json` 复制） |
| `paper_to_markdown/pipeline.py` | 核心转换引擎（被导入，不直接运行） |
| `paper_to_markdown/common.py` | 公共工具函数（被导入） |
| `paper_to_markdown/zotero_collections.py` | Zotero 数据库读取器（被导入） |
| `monitor.py` | 转换进度查看器 |
| `backfill.py` | 补齐缺失的 supporting PDF |

---

## 致谢

<table>
  <tr>
    <td align="center"><a href="https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/overview"><img src="https://img.shields.io/badge/Claude_Code-Anthropic-CC785C?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code"></a></td>
    <td>架构设计、代码实现和文档撰写均与 <strong>Claude Code</strong> 结对完成。</td>
  </tr>
  <tr>
    <td align="center"><a href="https://openai.com/index/codex/"><img src="https://img.shields.io/badge/Codex-OpenAI-412991?style=for-the-badge&logo=openai&logoColor=white" alt="OpenAI Codex"></a></td>
    <td><strong>OpenAI Codex</strong> 用于代码审查和交叉验证。</td>
  </tr>
</table>

> *"我们做了一个让 AI 代理读论文的工具——然后用 AI 代理把它做出来了。"*

## 许可证

MIT。详见 `LICENSE`。
