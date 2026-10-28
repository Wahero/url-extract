---
name: url-extract
description: 把链接（B站视频 / YouTube / 小红书 / 抖音 / GitHub 仓库 / 一般网页 / 腾讯微视）变成结构化 Markdown 精华文档，可选上传到 IMA 知识库。v2.6 新增：小红书视频笔记无登录态自动 CDN→ASR 抽取完整转写。触发词：精华、总结、提取、生成精华、B站精华、YouTube摘要、GitHub总结、小红书精华、抖音精华、网页精华。
allowed-tools: Read, Write, Bash, WebSearch
---

# URL Extract — 通用内容精华抽取

把任何链接变成一篇干净、结构化的 Markdown 精华文档。**支持 7 种来源**：B 站视频、YouTube、小红书、抖音、GitHub 仓库、一般网页、腾讯微视。**`--ima-raw` 上传完整 Markdown 到 IMA「RAW」知识库；`--ima-raw-md` 支持外部 Markdown 文件优先上传。**

> ⚠️ **学术测试版（Academic Preview）** — 当视频无字幕时，部分要点来自社区资料整合而非视频原声。正式参考请对照原始视频核实。

## 零配置快速上手

```bash
# 1. 安装依赖
pip install -r requirements.txt        # Python（含 tenacity 重试）
npm i -g defuddle                      # 可选：自动探测也可

# 2. 抽取任意链接 → 输出 JSON
python3 extract.py "https://b23.tv/xxx" --output result.json

# 3. 一键上传到 IMA（可选，需先 export 凭证）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw

# 4. B 站风控缓解（生产环境推荐）
python3 extract.py "https://b23.tv/xxx" --sessdata "你的SESSDATA" --wbi-sign on
```

## 支持来源

| 来源 | 检测规则 | 抽取方式 |
|---|---|---|
| **B站视频** | `bilibili.com` / `b23.tv` / `BV号` | 公共 API（视频信息/标签/字幕/评论）；SESSDATA cookie + wbi 签名 + tenacity 风控重试 |
| **YouTube 视频** | `youtube.com/watch?v=` / `youtu.be/` | yt-dlp dump-json + 字幕（推荐装 yt-dlp），无 yt-dlp 时降级到 noembed.com 公开代理 |
| **小红书笔记** | `xiaohongshu.com/discovery/item/` / `xhslink.com` / `xhslink.cn` | 短链重定向 → 视频 CDN 直链 → ffmpeg → Apple Speech 转写（**v2.6 无需登录拿到完整转写**）；图文笔记降级到 item_id 元信息 |
| **抖音视频** | `douyin.com/video/` / `v.douyin.com` / `iesdouyin.com` | 长链直接解析 video_id（无签名拿不到内容，强提示 WebSearch 补充） |
| **GitHub 仓库** | `github.com` | gh CLI → REST API → defuddle 三级降级 |
| **腾讯微视** | `weishi.qq.com` / 微信插件链接 | 微信 UA 模拟 + WebSearch 补充 |
| **一般网页** | 以上都不是 | defuddle CLI 一步提取（无 defuddle 时降级到 requests meta 提取） |

## 工作流程

### 步骤 1：运行抽取脚本

```bash
python3 extract.py "<链接>" --output /tmp/extract_result.json
```

脚本自动检测来源，输出 JSON。`source` 字段指示来源类型。

### 步骤 2：根据来源补充内容

读取 JSON 后按 `source` 字段走不同补充策略：

#### B站视频
- `subtitle.available=true` → 用 `subtitle.full_text` 作为核心素材
- `subtitle.available=false` → 用 WebSearch 搜索同标题社区文章 → defuddle 抓正文 → 整合还原；或 agent 自行生成完整 Markdown 后通过 `--ima-raw-md` 上传

**B站风控缓解**（推荐配置,生产环境必看）

- **症状**：extract 报 `BilibiliRiskControlError (code=-352/-412/-101)` 表明 IP 触发 B 站风控，3 次重试后仍失败
- **根因**：未登录 IP 高频请求被 B 站风控
- **解法**（三选一）:
  1. **注入 SESSDATA cookie**（最有效）：
     ```bash
     # 方式 1：CLI 参数
     python3 extract.py "https://b23.tv/xxx" --sessdata "你的SESSDATA值"
     # 方式 2：环境变量（推荐 cron 场景）
     export BILIBILI_SESSDATA="你的SESSDATA值"
     export BILIBILI_BILI_JCT="bili_jct值"  # 可选
     export BILIBILI_DEDEUSERID="你的UID"   # 可选
     ```
     获取方式：浏览器登录 B 站 → DevTools → Application → Cookies → 复制 `SESSDATA`/`bili_jct`/`DedeUserID` 字段值
  2. **开启 wbi 签名**（无需登录，但有 1 次额外 nav 接口调用）:
     ```bash
     python3 extract.py "https://b23.tv/xxx" --wbi-sign on
     ```
  3. **降低频率 + 错峰**：cron 场景避免高峰期
- **重试机制**：默认 3 次指数退避（1s/2s/4s），仅对 `BilibiliRiskControlError` 触发

#### YouTube 视频
- 优先：yt-dlp（需 `pip install yt-dlp`）拿完整元数据（title/channel/upload_date/view_count/like_count/description/字幕）
- 降级：noembed.com 公开代理，仅 title/author/thumbnail
- 字幕：自动下载 zh-Hans > zh-Hant > en 的 vtt 字幕，含轻量 WebVTT parser
- 输出：`templates/youtube.md.j2`（类似 B 站结构）

#### 小红书笔记（v2.6：视频笔记自动走 CDN→ASR 抽取完整转写）

**关键发现（2026-09-09）**：小红书短链 `xhslink.cn/o/xxx` 重定向时携带视频 CDN 直链：
- **iOS App 路径**：重定向到 `oia.xiaohongshu.com/oia?deeplink=...`，query 里是 URL-encoded JSON，含 h264/h265 `master_url`（带签名，无需登录就能下载）+ 封面 + 作者 UID
- **Web 路径**：xhslink.cn 短链直接返回 SPA 页面，`window.__INITIAL_STATE__` 嵌入完整 note JSON，视频 CDN URL 明文（`/` 写作 `\u002F`）

**抽取链路（自动运行，无需登录）**：

```
xhslink.cn 短链
  ↓ curl 重定向 (User-Agent: iPhone Safari)
oia.xiaohongshu.com/oia?deeplink=...
  ↓ _parse_xhs_deeplink() 抽 h264 master_url + 封面
下载 .mp4 (h264 优先，h265 兜底，限 100MB)
  ↓ ffmpeg 抽 wav (16kHz 单声道)
apple-speech transcribe --language zh-CN
  ↓ STT 转写
完整转写文本 + 时间分段 + 封面 + 元数据
```

**模板**：`templates/xiaohongshu.md.j2`（v2.6 升级：转写时显示完整文本 + 时间分段表格）

**字段**（成功路径返回）：
- `transcript`：完整转写文本
- `transcript_segments`：时间分段列表（每段含 `timestamp` + `substring`）
- `cover`：本地封面文件路径
- `video_url`：CDN 视频 URL
- `author_uid`：作者 UID
- `partial=False`：成功时不标记部分抽取

**降级**（CDN→ASR 链路失败时自动走）：
- `partial=True` + `pipeline_status='failed'` + `pipeline_stage`（失败阶段）
- 保留 v2.5 行为：只返回 item_id + 强 note 提示用户用 WebSearch 补充

**控制开关**（env var）：
- `XHS_VIDEO_CDN=0`：关闭视频 CDN 链路（默认开启）
- `XHS_ASR_ON_DEVICE=1`：强制 on-device STT（默认 server-side，速度慢但质量高；on-device 实测 90s 视频只返回最后 30s）

**外部依赖**（任意一个缺失时静默降级到 partial=True）：
- `ffmpeg`：抽 wav
- `apple-speech`：转写（macOS 14+ / iOS 17+ 自带）

**限制**：
- 仅视频笔记（`kind=='video'`）；图文笔记无 CDN 链接，走 partial 降级
- 视频下载上限 100MB
- ASR 转写超时 150s

#### 抖音视频（降级方案）
- 现实：需要 App 内置 UA + X-Sign 签名才能拿到内容
- 沙箱可做的：从长链 `douyin.com/video/{id}` 或 `modal_id=` 解析 video_id
- 模板：`templates/douyin.md.j2`（轻量，标记 partial=True）
- 用户补充方式：同小红书（WebSearch + defuddle）

#### GitHub 仓库
- 脚本已自动三级降级（gh CLI → REST API → defuddle）
- `note` 含 "defuddle" → 用了 defuddle 提取
- `note` 含 "全部失败" → 需换链接或人工补充

#### 腾讯微视
- **强制 WebSearch 补充**：用 `title` + `author` 搜索同话题公开报道
- 找到 URL 后用 defuddle 抓取报道正文

#### 一般网页
- defuddle 已一步提取完整正文（`content_markdown` 字段）
- 无需额外补充

### 步骤 3：生成 Markdown 文档

直接调用 `extract.py` 末尾的 `_build_markdown_content()` 即可（脚本本身已封装），或参照 `templates/` 下的来源模板。

输出文件名：`<来源前缀>精华_<标题>.md`（前缀见 `extract._SOURCE_PREFIX`）

---

## ⛔ 硬性规则

1. **去除 meta tag**：MD 不得含 YAML frontmatter、HTML `<meta>` 标签
2. **不生成弹幕内容**：B 站视频弹幕不纳入精华
3. **B站评论必含子回复**：`top_sub_reply` 点赞数接近主评论时必须展示
4. **链接必须真实**：参考资料所有链接来自实际抓取结果
5. **时区**：所有时间显示为北京时间（CST，UTC+8）
6. **搬运视频标原出处**：搬运翻译类视频标注原 YouTube 链接
7. **微视强制降级**：必须走 WebSearch 搜索补充
8. **GitHub 限流降级**：API 限流时自动降级到 defuddle
9. **优先 defuddle**：一般网页和内容补充优先 defuddle 而非 WebFetch
10. **文档尾部声明**：所有 MD 必须附学术测试版声明（即使字幕完整）

---

## IMA 知识库集成

### 凭证配置

```bash
export IMA_OPENAPI_CLIENTID="your_client_id"
export IMA_OPENAPI_APIKEY="your_api_key"
# 或运行引导脚本
python setup.py
```

> 凭证仅通过环境变量运行时传递，**不写入任何文件**。

获取地址：<https://ima.qq.com/agent-interface>

### 使用方式

```bash
# 上传 Markdown 到 RAW 知识库（推荐）
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw

# 上传 agent 生成的外部 Markdown
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw --ima-raw-md "./精华.md"

# 导入 URL 到指定知识库
python3 extract.py "https://example.com/article" --output result.json --upload-ima --ima-kb "我的知识库"

# 仅抽取（不导入 IMA）
python3 extract.py "https://b23.tv/xxx" --output result.json
```

### IMA v2.5.2 强化

- `api_call()` 自动重试：网络错误 / HTTP 5xx → tenacity 3 次指数退避（1s/2s/4s）
- 业务错误（HTTP 4xx / code != 0）抛 `ImaAPIBusinessError`，**不重试**
- 调优环境变量：`IMA_API_RETRY`（默认 3）/ `IMA_API_BACKOFF`（默认 1）
- COS 上传「SDK 优先 + Legacy 兜底」：`_cos_upload(prefer='auto')`，自动选 cos-python-sdk-v5

### IMA 模块文件

| 文件 | 说明 |
|---|---|
| `ima_client.py` | IMA OpenAPI 客户端 v1.4（tenacity 重试 + 类型注解 + ETag 判定） |
| `setup.py` | 凭证引导脚本，交互式输入 |

所有 IMA 请求仅发往 `https://ima.qq.com`，凭证永不出现在代码中。

---

## 依赖

- **Python 3.10+**（pyproject.toml 标 3.10+）：
  - 必需：`requests` + `beautifulsoup4` + `jinja2`（见 `requirements.txt`）
  - 可选（强烈推荐）：`tenacity`（B 站风控重试 + IMA API 重试）
  - 可选：`cos-python-sdk-v5`（IMA COS 上传 SDK 优先）
  - 可选：`yt-dlp`（YouTube 完整元数据 + 字幕）
- **Node.js 18+**（一般网页提取）：
  - 推荐：`defuddle`（`npm i -g defuddle`；脚本也支持自动探测 `npx defuddle`）
- **ffmpeg**（PATH）：小红书视频抽取链路需要
- **ASR backend**（小红书视频抽取需要，至少一个）：
  - **Apple 平台**（Mac / iOS）：自动用 `apple-speech`（Minis 沙箱内置 / Mac 装 Minis 客户端即可）
  - **跨平台**：装 `pip install openai-whisper`（自动 fallback）
  - **云端**：设 `GOOGLE_CLOUD_API_KEY` 环境变量（Google Cloud Speech-to-Text）

## ASR Backend 配置（v2.6.1 起跨平台兼容）

设计原则——**全平台兼容是基础，apple-speech 是 Mac/iOS 检测到时的优选路径，不限制项目整体功能**。

| 平台 | 推荐 ASR backend | 安装方法 |
|---|---|---|
| **Mac / iOS（Minis 沙箱）** | apple-speech（默认优选） | 沙箱内置；Mac 装 Minis 客户端即可 |
| **Linux / Windows / 其它 Mac** | whisper（默认 fallback） | `pip install openai-whisper` |
| **任意平台（云端）** | google-cloud-speech | 设 `GOOGLE_CLOUD_API_KEY` env var |

**控制开关**（env var）：

| env var | 默认 | 说明 |
|---|---|---|
| `XHS_ASR_BACKEND` | `auto` | `auto` 按优先级尝试可用 backend；也可强制指定 `apple-speech` / `whisper` / `google-cloud-speech` |
| `XHS_ASR_ON_DEVICE` | 未设 | apple-speech 专用：`1` 开启 on-device STT（实测有截断，默认 server-side） |
| `WHISPER_MODEL` | `base` | whisper 模型选择：`tiny` / `base` / `small` / `medium` / `large` |

**代码层面**：

- 新模块 `xhs_asr.py` 定义 `ASRBackend` 抽象基类
- 三个实现：`AppleSpeechBackend` / `WhisperBackend` / `GoogleCloudSpeechBackend`
- 调度函数：`transcribe_with_fallback(audio_path, language)` 自动按优先级尝试
- 检测函数：`is_apple_platform()` 返回 `True` 当且仅当 `apple-speech` 二进制存在

**Auto 模式 fallback 链**：

```
1. apple-speech（Mac/iOS）→ 可用时优先
  ↓ 失败 / 不可用
2. whisper（任意平台）→ 装了 openai-whisper 即可用
  ↓ 失败 / 不可用
3. google-cloud-speech（云端）→ 有 API key 即可用
  ↓ 全失败
→ pipeline stage=transcribe，partial=True 降级
```

## 项目结构

```
url-extract/
├── SKILL.md                  # 本文件
├── README.md                 # 项目说明
├── CHANGELOG.md              # 完整版本历史
├── REFACTOR_PROGRESS.md      # 2026-08-07 重构工作汇报
├── extract.py                # 主入口脚本（v2.6：XHS 视频 CDN→ASR + 147 测试覆盖）
├── ima_client.py             # IMA 客户端 v1.4
├── setup.py                  # IMA 凭证引导
├── pyproject.toml            # Python 包元数据
├── requirements.txt          # 依赖清单
├── templates/                # Markdown 模板（Jinja2，7 个）
│   ├── bilibili.md.j2
│   ├── github.md.j2
│   ├── webpage.md.j2
│   ├── weishi.md.j2
│   ├── youtube.md.j2
│   ├── xiaohongshu.md.j2
│   └── douyin.md.j2
├── tests/                    # 147 个单元测试
│   ├── test_bilibili_cookie_retry.py   (24 用例)
│   ├── test_new_sources.py             (43 用例，含 XHS v2.6 16 个)
│   ├── test_ima_client.py              (7 用例)
│   ├── test_ima_retry.py               (22 用例)
│   ├── test_cos_sdk_etag.py            (6 用例)
│   ├── test_defuddle_fix.py            (5 用例)
│   ├── test_url_validation.py          (17 用例)
│   ├── test_refactor_13.py             (12 用例)
│   ├── test_templates.py               (10 用例)
│   └── fixtures/
└── .github/workflows/test.yml   # GitHub Actions CI（pytest 3.10/3.11/3.12）
```

## 测试与 CI

- **147 个测试**覆盖：B 站风控 / 新来源（含 XHS v2.6 视频抽取）/ IMA 重试 / COS SDK ETag / 模板渲染 / URL 验证 / defuddle 修复
- **CI**: GitHub Actions 跑 pytest 矩阵（Python 3.10 / 3.11 / 3.12）
- **本地跑测试**：
  ```bash
  pip install -r requirements.txt
  python3 -m pytest tests/ -v
  ```

## 版本历史

详见 [CHANGELOG.md](CHANGELOG.md)

最近一次大规模重构：2026-08-07（详见 [REFACTOR_PROGRESS.md](REFACTOR_PROGRESS.md)）
- 8 个 PR 合并（PR #8-15）
- 4 个 issue 关闭
- 13 / 33 报告项修复
- 130 个测试（0 回归）
