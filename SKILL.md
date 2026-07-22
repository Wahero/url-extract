---
name: url-extract
description: 通用内容精华抽取 v2.5——从B站视频、GitHub仓库、一般网页URL或腾讯微视链接中抽取精华内容，生成结构化Markdown文档，支持上传Markdown到IMA知识库（含RAW自动导入+去重）。v2.5 修复 B站无字幕时 markdown 不完整 bug，新增 --ima-raw-md 外部 Markdown 文件上传。触发词："精华"、"总结"、"提取"、"生成精华"、"B站精华"、"GitHub总结"、"网页精华"等。当用户提供任何链接并要求生成精华/总结/抽取内容时触发。
allowed-tools: Read, Write, Bash, WebSearch
---

# URL Extract — 通用内容精华抽取 v2.5

从多种来源抽取精华内容，生成干净的结构化 Markdown 文档。支持：B站视频、GitHub 仓库、一般网页 URL、腾讯微视/视频。**`--ima-raw` 上传完整 Markdown 文档到「RAW」个人知识库（非 URL 导入）；`--ima-raw-md` 支持指定外部 Markdown 文件优先上传。**

**v2.5 核心变更：修复 `_build_markdown_content()` 对 B站无字幕视频只输出空壳的 bug，重写为来源感知的完整结构化输出；新增 `--ima-raw-md` 参数，支持指定外部 Markdown 文件优先上传 agent 生成的高质量精华文档。**
**v2.4 核心变更：IMA 凭证改为仅从环境变量读取，不持久化存储；--ima-raw 上传完整 Markdown 文档（四步流程：create_media → COS → add_knowledge）而非 URL 导入。**
**v2.3 核心变更：新增 `--ima-raw` 自动导入 IMA「RAW」个人知识库（导入前搜索标题/URL 去重）。**
**v2.2 核心变更：集成 IMA OpenAPI，抽取结果可自动导入用户知识库（--upload-ima + --ima-kb）。**
**v2.1 核心变更：集成 defuddle CLI 替代 WebFetch，实现本地化网页内容提取，输出更干净、更省 token。**

## 设计初衷

太多资源混杂着无关痛痒的信息。深夜床上不适合看视频、只想快速了解一个仓库、被标题吸引点进去却全是废话——这个 skill 把任何链接变成一篇纯粹的结构化精华文章。

---

## defuddle CLI — 网页内容提取引擎

defuddle 是由 Obsidian 创始人 kepano 开发的网页内容提取工具，已安装在本地 Node.js 环境中。它自动去除侧栏、广告、页脚、导航等噪音，返回干净的 Markdown 和结构化元数据。

### 调用方式

```bash
# 提取网页内容为 JSON（含元数据+正文Markdown）
cd ~/.workbuddy/binaries/node/workspace && NODE_PATH=node_modules npx defuddle parse "<URL>" --json

# 提取网页内容为纯 Markdown
cd ~/.workbuddy/binaries/node/workspace && NODE_PATH=node_modules npx defuddle parse "<URL>" --markdown
```

### defuddle vs WebFetch 对比

| 维度 | WebFetch | defuddle CLI |
|------|---------|-------------|
| 提取方式 | AI 模型处理 HTML→markdown | 本地算法提取（无 AI 模型） |
| 输出质量 | 含侧栏/广告/导航等噪音 | 已清洗，仅保留正文 |
| Token 消耗 | 高（噪音内容也被计入） | 低（~节省 50-70% token） |
| 速度 | 较慢（需 AI 模型处理） | 快（本地算法，秒级返回） |
| 元数据 | 仅标题/摘要 | title/author/description/domain/published/wordCount 等 |

---

## 来源路由

根据用户提供的链接，自动检测来源类型并执行对应策略：

| 来源 | 检测规则 | 抽取方式 | 内容补充策略 |
|---|---|---|---|
| **B站视频** | `bilibili.com` / `b23.tv` / BV号 | 脚本 `extract.py` 调用公开 API | 脚本自动生成完整结构（视频概览表格/字幕/标签/评论）；字幕缺失时建议 agent 生成精华内容，通过 `--ima-raw-md` 上传 |
| **GitHub 仓库** | `github.com` | 脚本 gh CLI → REST API → **defuddle** 三级降级 | Stars/描述/Topics 等元数据 + README 内容 |
| **腾讯微视** | `weishi.qq.com` / `v.qq.com` 微信插件 | 脚本用微信 UA 模拟抓页面 HTML | **必须**用 WebSearch 搜索同话题报道 → defuddle 抓取报道正文 |
| **一般网页** | 以上都不是 | **defuddle** 直接提取（一步到位） | 无需额外补充，defuddle 已返回完整正文+元数据 |

---

## 工作流程

### 步骤 1：运行抽取脚本

```bash
PYTHONPATH="<skill_dir>/scripts/deps" <managed_python> "<skill_dir>/scripts/extract.py" "<链接>" --output /tmp/extract_result.json
```

- `<skill_dir>` 替换为本 skill 的实际安装目录（`~/.workbuddy/skills/url-extract/`）
- `<managed_python>` 替换为管理版 Python 路径

脚本自动检测来源并抽取基础元信息。对于一般网页，脚本已通过 defuddle 一步提取了完整正文（`content_markdown` 字段）。输出 JSON 的 `source` 字段指示来源类型。

### 步骤 2：根据来源执行内容补充

读取脚本输出的 JSON，按 `source` 字段走不同补充策略：

#### B站视频

关键字段 `subtitle.available`：

| available | 处理方式 |
|---|---|
| `true` | 使用 `subtitle.full_text` 作为核心素材 |
| `false` | 用 WebSearch 搜索视频标题 + 关键标签 → 找到社区文章 URL → 用 **defuddle** 抓取文章正文，整合还原视频讲解内容；或 agent 生成完整精华 Markdown 后通过 `--ima-raw-md` 上传 |

**defuddle 抓取社区文章：**
```bash
cd ~/.workbuddy/binaries/node/workspace && NODE_PATH=node_modules npx defuddle parse "<社区文章URL>" --json
```

#### GitHub 仓库

- 脚本已自动执行三级降级（gh CLI → REST API → defuddle）
- 如果 JSON 中 `note` 包含 "defuddle"，说明使用了 defuddle 提取，`content_markdown` 字段已包含 README 内容
- 如果三级全部失败（`note` 含 "全部失败"），需人工补充或换链接重试

#### 腾讯微视

- **强制 WebSearch 补充**：用 `title` + `author` 搜索同话题的公开报道（搜狐、新浪、头条、抖音等平台）
- 搜索到报道 URL 后，用 **defuddle** 抓取报道正文（而非 WebFetch）
- 如果 `title` 为空，提示用户提供视频描述辅助搜索

**defuddle 抓取报道：**
```bash
cd ~/.workbuddy/binaries/node/workspace && NODE_PATH=node_modules npx defuddle parse "<报道URL>" --json
```

#### 一般网页

- **无需额外补充**：defuddle 已在步骤 1 中一步提取了完整元数据 + 正文 Markdown
- 直接使用 JSON 中 `content_markdown` 字段作为核心素材
- 元数据（`title`/`author`/`desc`/`domain`/`published`/`word_count`）可直接用于文档头部

### 步骤 3：生成 Markdown 文档

根据来源类型使用对应的文档模板：

#### B站视频模板

```markdown
# <视频标题>

> 来源：B站视频 · UP主：<UP主名>
> 原始链接：<视频URL>
> 发布时间：<发布时间>
> 视频时长：<时长>

---

## 一、视频概览
（结构化数据表格：标题/UP主/BV号/标签/播放数据/视频简介）

## 二、精华内容
（分小节呈现：事件背景、核心思想、关键要点、技术细节等）

## 三、最高点赞评论
（展示 top_replies，含高赞子回复 top_sub_reply——B站特色）

## 四、参考资料
（视频原链 + 实际抓取的社区文章链接）

*本文档由视频内容及公开资料整合生成，仅作信息整理与学习参考之用。*
```

#### GitHub 仓库模板

```markdown
# <owner/repo>

> 来源：GitHub · 链接：<URL>

## 一、仓库概览
（结构化数据表格）

## 二、项目精华
（README 核心内容提炼——来自 defuddle content_markdown 或 API description）

## 三、参考资料
```

#### 一般网页/微视模板

```markdown
# <标题>

> 来源：<来源描述> · 链接：<URL>
> 作者：<author>（如有）
> 发布日期：<published>（如有）

## 一、概览
## 二、精华内容
（直接使用 defuddle 提取的 content_markdown，按主题分小节）
## 三、参考资料
```

### 步骤 4：输出文件

文件名格式：`<来源前缀>精华_<标题>.md`

| 来源 | 前缀 | 示例 |
|---|---|---|
| B站 | `B站视频精华_` | `B站视频精华_xxx.md` |
| GitHub | `GitHub精华_` | `GitHub精华_xxx.md` |
| 微视 | `视频精华_` | `视频精华_xxx.md` |
| 网页 | `网页精华_` | `网页精华_xxx.md` |

标题中去除特殊字符，保留中文、英文、数字、连字符。长度不超过 60 字。

---

## ⛔ 硬性规则

1. **去除 meta tag**：MD 文档不得包含 YAML frontmatter、HTML `<meta>` 标签。文档必须以 `# 标题` 开头。
2. **不生成弹幕内容**：B站视频的弹幕不纳入精华文档。
3. **B站评论必含子回复**：当 `top_sub_reply` 点赞数接近或超过主评论时，必须展示——这是 B 站评论生态的特色。
4. **链接必须真实有效**：文末参考资料所有链接来自实际抓取结果，不得编造。
5. **时区**：所有时间显示为北京时间（CST，UTC+8）。
6. **搬运视频标原出处**：B站搬运翻译类视频，在文档中标注原 YouTube/原视频链接。
7. **微视强制降级**：微视来源必须走 WebSearch 搜索补充，不可仅凭页面解析的元信息输出。
8. **GitHub 限流降级**：当 API 限流时，脚本自动降级到 defuddle 提取 README 内容。
9. **优先 defuddle**：对于一般网页和内容补充场景，优先使用 defuddle CLI 而非 WebFetch，以获得更干净的内容和更低的 token 消耗。

---

## IMA 知识库集成（v2.2 新增，v2.4 重构）

抽取完成后，可通过 `--upload-ima` 将源链接导入指定知识库，或通过 `--ima-raw` 上传完整 Markdown 文档到 IMA「RAW」个人知识库。**凭证仅通过环境变量传递，不持久化存储。**

### 凭证配置

```bash
# 设置环境变量（每次会话需重新设置）
export IMA_OPENAPI_CLIENTID="your_client_id"
export IMA_OPENAPI_APIKEY="your_api_key"

# 或运行引导脚本（交互式输入，仅设置当前会话）
python setup.py
```

> **安全说明**：本项目不会将凭证写入任何文件。凭证仅通过环境变量在运行时传递。

获取地址：https://ima.qq.com/agent-interface （微信登录后，Client ID 自动显示，API Key 需点击「获取 API Key」按钮生成）

### 使用方式

```bash
# 上传 Markdown 文档到 RAW 知识库（v2.5，推荐）
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw

# 上传 agent 生成的外部 Markdown 文档到 RAW（v2.5 新增）
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw --ima-raw-md "./B站视频精华_xxx.md"

# 导入 URL 到指定知识库（v2.2）
python3 extract.py "https://example.com/article" --output result.json --upload-ima --ima-kb "我的知识库"

# 仅抽取（不导入 IMA），与旧版完全兼容
python3 extract.py "https://b23.tv/xxx" --output result.json
```

`--ima-raw` 关键特性（v2.5）：
- 上传完整 Markdown 精华文档（非 URL 导入，v2.5 来源感知结构化输出）
- 四步流程：check_repeated → create_media → COS 上传 → add_knowledge
- 导入前检查重名和内容去重，已存在则跳过
- 上传失败时自动降级为 URL 导入
- 无需手动指定知识库名称，适合自动化管道
- **新增 `--ima-raw-md <FILE>`**：指定外部 Markdown 文件优先上传（agent 生成的高质量精华文档）

### IMA 模块文件

| 文件 | 说明 |
|---|---|
| `ima_client.py` | IMA OpenAPI Python 客户端 v1.2，仅环境变量认证，封装 API 调用、知识库搜索去重、Markdown 上传 |
| `setup.py` | 凭证引导脚本，交互式输入，仅设置当前会话环境变量，不持久化 |

所有 IMA API 请求仅发往官方端点 `https://ima.qq.com`，凭证永不出现在代码中。

---

## 脚本依赖

- Python 3.11+ + `requests` + `beautifulsoup4`（隔离安装在 `<skill_dir>/scripts/deps/`）
- Node.js + `defuddle` + `linkedom`（安装在 `~/.workbuddy/binaries/node/workspace/`）

---

## 版本历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.5 | 2026-07-22 | 修复 `_build_markdown_content()` 对 B站无字幕视频只输出空壳的 bug，重写为来源感知完整结构化输出（视频概览表格/字幕全文/标签/评论精选/仓库概览等）；新增 `--ima-raw-md` 参数，支持指定外部 Markdown 文件优先上传 agent 生成的高质量精华文档 |
| v2.4 | 2026-07-21 | IMA 凭证改为仅环境变量，不持久化存储；`--ima-raw` 上传完整 Markdown 文档（create_media → COS → add_knowledge）；修复 API 字段映射 bug |
| v2.3 | 2026-07-20 | 新增 `--ima-raw`：抽取后自动导入 IMA「RAW」个人知识库，导入前搜索去重；重构 `ima_client.py` 新增 `find_kb_by_name`/`check_duplicate` |
| v2.2 | 2026-07-20 | 集成 IMA OpenAPI：新增 `ima_client.py` + `setup.py`，支持 `--upload-ima` 一键导入知识库；凭证通过环境变量/配置文件分离管理 |
| v2.1 | 2026-07-20 | 集成 defuddle CLI 替代 WebFetch：网页一步提取、GitHub降级、B站/微视内容补充均用 defuddle，节省 ~50-70% token |
| v2.0 | 2026-07-20 | 通用版发布：支持 B站/GitHub/网页/微视 四种来源，平台无关设计 |
| v1.0 | 2026-07-19 | WorkBuddy 专版（bili-extract），仅支持 B站视频 |
