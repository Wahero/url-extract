<div align="center">

# URL Extract

### 把「看不完」的内容，变成「读得完」的精华
### Turn "too much to watch" into "quick to read"

不用再花 40 分钟看一条 8 分钟就能读完的视频。
贴一条链接，拿回一篇干净、有结构、能存档的文字。

`B站` · `YouTube` · `小红书` · `抖音` · `微视` · `GitHub` · `任意网页`

[![Tests](https://img.shields.io/badge/tests-199%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![CI](https://github.com/Wahero/url-extract/actions/workflows/test.yml/badge.svg)](.github/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.6.2-blue)](CHANGELOG.md)

**[简体中文](#-简体中文) · [English](#-english)**

</div>

---

<a id="-简体中文"></a>

## 🇨🇳 简体中文

### 这是什么？

你的一天，有多少时间被"无聊但好像该看"的内容吃掉了？

- 通勤时刷到的 30 分钟播客视频，其实核心就 5 条结论
- 收藏夹里 200 条小红书，想说"以后再看"，从此再也没打开
- 深夜躺在床上，屏幕亮得刺眼，但你真的还想再看一个小时的视频吗
- 想快速判断一个 GitHub 项目值不值得用，结果在读了一堆安装说明

**URL Extract 只做一件事：把任何一条链接，变成一篇可以直接阅读、可以直接存档的精华文字。**

不是逐字稿，不是机器翻译，不是一堆原始字幕堆砌。
是经过整理、分节、带概览的结构化文字 —— 你打开就能读完，读完就懂。

### 三种用法，看你当下的处境

#### 🌙 现在不方便看视频

在地铁上、在被窝里、在开会前的五分钟。把链接丢进去，几分钟后拿回一篇能直接读的精华。**眼睛比耳朵自由** —— 可以扫读、可以回看、可以在任何一秒钟停下。

#### 📌 这条内容很好，但今天没时间

一键抽取 → 存成文字 → 躺进你的知识库。**好东西不漏，时间不挤。**

#### 🗂 我要的是一份能搜索的资料库

一天看十条，一个月就是三百条，半年后你只会记得"好像看过"。抽成文字后可以直接归档（目前支持 **IMA 知识库**一键入库），从此**可以被搜到、被引用、被整理**，而不是消失在收藏夹深处。

### 它支持什么

| 你手上的链接 | 你会拿到 |
|---|---|
| **B 站视频** `b23.tv/xxx` | 视频概览 + 字幕内容整理 + 标签与评论要点 |
| **YouTube** `youtu.be/xxx` | 完整字幕 + 播放量 / 点赞 / 时长 / 发布日期 |
| **小红书** 视频笔记 | **完整语音转写** + 分段 + 封面 + 作者信息（无需登录） |
| **小红书** 图文笔记 | 基础信息（正文抽取仍有限，见下方诚实说明） |
| **抖音** `douyin.com/video/xxx` | 视频 ID 与基础信息，正文可能不完整 |
| **腾讯微视** | 基础信息 + 公开报道补充 |
| **GitHub 仓库** | 这个项目到底是做什么的、值不值得用 |
| **任意网页** 博客 / 新闻 / 公众号文章 | 去广告去杂讯后的正文精华 |

> 一次贴一条，输出一篇。多个链接也可以依次批量跑。

### 输出长什么样

固定三段式，干净、没有噪音、没有乱七八糟的格式标记：

```markdown
# 标题

> 来源 · 作者 · 时长 · 发布时间

## 一、概览
    一眼看懂这篇文章/这条视频在讲什么（含关键数据表）

## 二、精华内容
    分小节整理的核心信息，不再是散乱的逐字稿

## 三、参考资料
    所有来源链接，方便你回去核对原文
```

**你能拿它做什么：** 直接读 / 存成 Markdown / 丢进知识库 / 交给 AI 继续加工。

### 接上你的知识库（目前支持 IMA）

| 你想怎么做 | 效果 |
|---|---|
| 想要一份**完整的精华文档**存进知识库 | `--ima-raw`：文档以 Markdown 形式上传，结构完整、可搜索 |
| 想自己先改一改再入库 | `--ima-raw --ima-raw-md ./你的文档.md`：优先上传你的版本 |
| 只想**记下这条原始链接** | `--upload-ima`：把网址导入指定知识库 |

**入库准备（只需一次）：** 到 [IMA 开放平台](https://ima.qq.com/agent-interface) 微信扫码登录，拿到 Client ID 与 API Key，设成环境变量即可。**凭证不会写进任何文件、不会留存，会话结束即失效。**

### 怎么用起来？

**方式一：作为 AI 技能安装（推荐）**

如果你用 AI 编程助手（Claude Code、Codex 等），它可以作为一项技能直接装上，之后你只需要说一句"帮我把这个链接变精华"：

```bash
npx skills add Wahero/url-extract
```

**方式二：作为独立命令行工具**

```bash
pip install -r requirements.txt

python3 extract.py "https://b23.tv/xxx" -o result.json

# 一键上传到 IMA 知识库（需先设置凭证）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"
python3 extract.py "https://b23.tv/xxx" -o result.json --ima-raw
```

需要的东西不多，主要依赖 Python 3.10+。YouTube 建议额外装 `yt-dlp`，网页正文抽取建议装 `defuddle`。缺了也能跑，只是效果会打折 —— 程序会自动降级，不会直接失败。

### 诚实说明：它能做到什么，做不到什么

我们不想让你用完才发现"原来不行"。

| 情况 | 实际表现 |
|---|---|
| **小红书图文笔记** | 正文抽取仍然有限，目前主要能拿到基础信息；**视频笔记**才能完整转写 |
| **抖音** | 没有签名的情况下拿不到完整正文，只能给出基础信息并标注"内容不完整" |
| **YouTube 字幕** | 依赖自动生成的中文字幕；**完全没有字幕时无法转写** |
| **小红书语音转写** | 依赖系统级语音识别能力（macOS 14+ / iOS 17+）；其它系统上会自动降级，只给基础信息 |
| **语音转写本身** | 机器识别，难免有错字漏字。**医学、法律、金融等专业内容，请务必回看原视频或咨询专业人士** |
| **内容来源** | 当某条链接本身无字幕、无正文时，部分内容会由公开资料整合而来，**并非全部来自原视频的音频或画面** —— 需要精确引用时请核对原文 |

一句话：**它是一把很好的"省时间"工具，不是"替代原始信息"的工具。**

### 许可与商用（License & Commercial）

- 本仓库的**开源版本**以 [**MIT License**](LICENSE) 发布（SPDX: `MIT`），免费使用、修改、分发，只需保留版权与许可声明。
- **第三方付费包与高级版本**（如将来在 Agensi.io 等市场上架的 Premium Pack）以**独立的商业许可**发布，不属于本 MIT 开源仓库的一部分。
- 项目名称 "URL Extract" 与相关标识不随 MIT 许可授权，未经授权不得用于衍生项目的宣传或冒充官方。
- 本项目与 B 站、YouTube、小红书、抖音、腾讯等平台**无任何隶属或合作关系**，请遵守各平台服务条款，仅将本工具用于**个人学习与研究**，尊重原作者版权。
- 问题反馈与安全漏洞报告：请通过 [GitHub Issues](https://github.com/Wahero/url-extract/issues) 提交。

### 声明

- 当前版本为**学术测试版（Academic Preview）**，不建议用于生产环境或关键业务。
- 抽取质量受原内容质量影响很大 —— 原视频本身水分多，抽出来也只能是"浓缩的水"。

---

<div align="center">

**把时间还给自己。**
内容看不完，不代表你要看完全部。

</div>

---

<a id="-english"></a>

## 🇬🇧 English

### What is this?

How much of your day gets eaten by content you "feel you should watch"?

- A 30-minute podcast video from your commute that really has just 5 takeaways
- 200 saved Xiaohongshu posts marked "read later" — never opened again
- Lying in bed at night, screen too bright, wondering if you really want another hour of video
- Trying to judge whether a GitHub repo is worth using, and getting stuck in install docs

**URL Extract does exactly one thing: turn any link into clean, structured, archivable text.**

Not a raw transcript. Not machine translation. Not a pile of subtitles.
A structured article — organized, sectioned, with an overview — ready to read the moment it arrives.

### Three ways to use it

#### 🌙 When you can't watch a video right now

On the subway, in bed, five minutes before a meeting. Drop in a link, get back a readable digest in minutes. **Your eyes are freer than your ears** — skim, re-read, pause at any second.

#### 📌 Great content, but no time today

Extract → save as text → straight into your knowledge base. **Nothing gets lost, no time gets squeezed.**

#### 🗂 You want a searchable library

Ten items a day is three hundred a month; six months later all you remember is "I think I saw that." Once extracted, you can archive directly (currently supports one-click upload to the **IMA Knowledge Base**) — searchable, quotable, organized, instead of buried in your bookmarks.

### What it supports

| Your link | What you get |
|---|---|
| **Bilibili** `b23.tv/xxx` | Video overview + organized subtitles + tags & comment highlights |
| **YouTube** `youtu.be/xxx` | Full subtitles + views / likes / duration / publish date |
| **Xiaohongshu (RED)** video notes | **Full speech-to-text transcript** + segments + cover + author info (no login required) |
| **Xiaohongshu** image-text notes | Basic info only (text extraction still limited — see honest notes below) |
| **Douyin** `douyin.com/video/xxx` | Video ID and basic info; full text may be unavailable |
| **Tencent Weishi** | Basic info + public-report enrichment |
| **GitHub repos** | What this project actually does, and whether it's worth using |
| **Any web page** blogs / news / articles | Clean body text, ads and noise removed |

> One link in, one article out. Multiple links can be processed in batch, one by one.

### What the output looks like

A fixed three-part structure — clean, no noise, no format junk:

```markdown
# Title

> Source · Author · Duration · Published

## 1. Overview
    What this is about at a glance (with key data table)

## 2. Key Content
    Core information organized into sections — not a messy transcript

## 3. References
    All source links, so you can verify against the original
```

**What you can do with it:** read it / save as Markdown / feed your knowledge base / hand it to another AI.

### Connect your knowledge base (currently IMA)

| What you want | How |
|---|---|
| Archive the **full digest document** | `--ima-raw`: uploads structured, searchable Markdown |
| Edit it yourself first | `--ima-raw --ima-raw-md ./your.md`: your version takes priority |
| Just **remember the link** | `--upload-ima`: imports the URL into a chosen knowledge base |

**One-time setup:** sign in at the [IMA Open Platform](https://ima.qq.com/agent-interface) with WeChat, get a Client ID and API Key, and set them as environment variables. **Credentials are never written to any file and never persisted — they expire when the session ends.**

### How to use it

**Option 1: Install as an AI skill (recommended)**

If you use an AI coding assistant (Claude Code, Codex, etc.), install it as a skill and just say "turn this link into a digest":

```bash
npx skills add Wahero/url-extract
```

**Option 2: Run it yourself**

```bash
pip install -r requirements.txt

python3 extract.py "https://b23.tv/xxx" -o result.json

# One-click upload to IMA (set credentials first)
export IMA_OPENAPI_CLIENTID="your-client-id"
export IMA_OPENAPI_APIKEY="your-api-key"
python3 extract.py "https://b23.tv/xxx" -o result.json --ima-raw
```

Requirements are light: Python 3.10+. `yt-dlp` is recommended for YouTube, `defuddle` for web page extraction. Everything degrades gracefully — missing extras won't break the run, just reduce quality.

### Honest notes: what it can and cannot do

We'd rather tell you now than have you find out later.

| Situation | Actual behavior |
|---|---|
| **Xiaohongshu image-text notes** | Text extraction is limited; mostly basic info. Only **video notes** get full transcription |
| **Douyin** | Without request signing, only the video ID and basic info — marked as "partial" |
| **YouTube subtitles** | Depends on auto-generated Chinese subtitles; **no subtitles = no transcript** |
| **Xiaohongshu speech-to-text** | Requires system-level speech recognition (macOS 14+ / iOS 17+); other platforms degrade to basic info |
| **Transcription accuracy** | Machine ASR inevitably has errors. **For medical, legal, or financial content, always check the original video or consult a professional** |
| **Content sourcing** | When a link has no subtitles or body text, parts of the digest are compiled from public sources — **not all from the video's own audio or visuals**. Verify against the original before precise citation |

In one sentence: **this is a great time-saving tool, not a replacement for the original content.**

### License & Commercial Use

- The **open-source version** in this repository is released under the [**MIT License**](LICENSE) (SPDX: `MIT`) — free to use, modify, and distribute, provided the copyright and license notice are retained.
- **Third-party premium packs** (e.g., a future Premium Pack listed on marketplaces like Agensi.io) are distributed under a **separate commercial license** and are not part of this MIT-licensed repository.
- The name "URL Extract" and related branding are **not** licensed under MIT and may not be used to promote derivative projects or imply official endorsement.
- This project is **not affiliated with** Bilibili, YouTube, Xiaohongshu, Douyin, Tencent, or any other platform. Please comply with each platform's terms of service, use this tool for **personal learning and research only**, and respect original authors' copyrights.
- Bug reports and security disclosures: please use [GitHub Issues](https://github.com/Wahero/url-extract/issues).

### Disclaimer

- The current version is an **Academic Preview** — not recommended for production or business-critical use.
- Output quality depends heavily on the source material — squeeze watery content and you get concentrated water.

---

<div align="center">

**Give your time back to yourself.**
You don't have to finish everything to have read enough.

</div>

---

<sub>License: MIT · 中文 / English · Feedback and new source support are always welcome · 欢迎提交新的来源支持与改进建议</sub>
