# URL Extract — 通用内容精华抽取

> 把视频、网页、GitHub 仓库变回纯粹的精华文字。夜深了不想看视频？信息过载只需要干货？这就是为你准备的。**v2.5.2：支持 7 种来源（新增 YouTube / 小红书 / 抖音）、B 站风控缓解（tenacity 重试 + wbi 签名 + SESSDATA cookie）、IMA API tenacity 重试、工程化重构（异常化错误处理 / lazy init / URL 验证 / 类型注解 / 130 个单元测试）。**

[![Tests](https://img.shields.io/badge/tests-130%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![CI](https://github.com/Wahero/url-extract/actions/workflows/test.yml/badge.svg)](.github/workflows/test.yml)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

> ⚠️ **重要声明 — 请务必阅读**
>
> **本版本（v2.5.2）为学术测试版（Academic Preview），请勿用于生产环境。**
>
> 当视频无字幕时，文档中的部分内容系从社区中相同或相似标题的公开资料处获取并整合而成，**并非直接由视频本身的音频或画面提取**。这意味着：
>
> - 部分要点可能来自社区作者的二次解读，而非视频创作者的原话
> - 视频中独有的演示画面、语气强调、即兴发挥等内容无法被覆盖
> - 文档的结构化呈现可能掩盖内容可信度的局限性
>
> 待 v2.6 版本（含音频转录层）发布后，此限制将被大幅改善。
>
> **如需用于正式参考、引用或决策，请务必对照原始视频核实。**

---

## 为什么需要它？

外面太多资源——B站视频、YouTube、小红书、抖音、GitHub 仓库、一般博客、微信公众号链接——混杂着大量无关痛痒的信息。有时候深夜躺在床上不适合看视频，有时候只想快速了解一个仓库做了什么，有时候被标题吸引进去却发现全是废话。

**URL Extract 做的就是一件事：把任何链接变成一篇干净、结构化的精华文章。**

## 支持来源（7 种）

| 来源 | 示例 | 处理方式 |
|---|---|---|
| **B站视频** | `https://b23.tv/xxx` | 公开 API（视频信息 / 标签 / 字幕 / 评论）；支持 SESSDATA cookie + wbi 签名 + tenacity 风控重试 |
| **YouTube 视频** | `https://youtu.be/xxx` | yt-dlp dump-json + 字幕（推荐装 yt-dlp）；无 yt-dlp 时降级到 noembed.com 公开代理 |
| **小红书笔记** | `https://xiaohongshu.com/discovery/item/xxx` | 短链重定向链解析 item_id（无登录态只能拿到元信息，标记 partial） |
| **抖音视频** | `https://douyin.com/video/xxx` | 长链直接解析 video_id（无签名只能拿到元信息，标记 partial） |
| **GitHub 仓库** | `https://github.com/user/repo` | gh CLI → REST API → defuddle 三级降级 |
| **腾讯微视** | `https://weishi.qq.com/xxx` | 微信 UA 模拟 + 公开报道搜索补充 |
| **一般网页** | 小红书 / 博客 / 新闻等 | defuddle 本地提取（无 defuddle 时降级到 requests meta 提取） |

## 核心设计：多级降级

不依赖单一数据源。当首选方式不可用时，自动降级：

```
B站：     API + Cookie + wbi 签名 → tenacity 重试（风控 1s/2s/4s）→ 社区文章搜索
YouTube： yt-dlp (dump-json + 写自动字幕) → noembed.com 公开代理
小红书：  重定向链解析 item_id → WebSearch 补充内容
抖音：    长链直接解析 video_id → WebSearch 补充内容
GitHub：  gh CLI → REST API → defuddle 抓 README
微视：    微信 UA 模拟 → 公开报道搜索
网页：    defuddle → requests meta → 用户手动补
```

## IMA 知识库集成（v2.2+，v2.5.2 强化）

抽取完成后可一键导入 IMA 知识库。**凭证通过环境变量传递，不写入文件、不持久化存储。**

```bash
# 1. 设置凭证（每次会话需重新设置）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 2. 抽取 + 上传 Markdown 到 RAW 知识库
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw

# 3. 或导入到指定知识库（URL 导入）
python3 extract.py "https://example.com/article" --output result.json --upload-ima --ima-kb "我的知识库"

# 4. 使用外部 Markdown 文件上传到 RAW（v2.5 新增）
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw --ima-raw-md "./精华文档.md"

# 5. B站风控缓解（生产环境推荐）
python3 extract.py "https://b23.tv/xxx" --output result.json \
    --sessdata "你的SESSDATA" --wbi-sign on

# 6. 或仅抽取（不导入 IMA）
python3 extract.py "https://b23.tv/xxx" --output result.json
```

### `--ima-raw` 与 `--upload-ima` 的区别

| 参数 | 导入方式 | 内容 |
|---|---|---|
| `--ima-raw` | 上传 Markdown 文件（四步流程：create_media → COS → add_knowledge） | 完整精华 Markdown 文档（v2.5 来源感知结构化输出） |
| `--ima-raw-md <FILE>` | 配合 `--ima-raw` 使用，指定外部 Markdown 文件 | 优先上传 agent 生成的高质量精华文档 |
| `--upload-ima` | URL 导入（import_urls） | 原始网址链接 |

### IMA v2.5.2 强化（issue #5 + PR #15）

- `api_call()` 加 tenacity 重试：网络错误 / HTTP 5xx 自动重试 3 次（指数退避 1s/2s/4s）
- 业务错误（HTTP 4xx / code != 0）抛 `ImaAPIBusinessError`，**不重试**
- 通过环境变量 `IMA_API_RETRY` / `IMA_API_BACKOFF` 可调
- `_cos_upload_sdk` 修复：不再传 `ContentLength`（int 触发问题），用 `ETag` 判定成功
- COS 上传「SDK 优先 + Legacy 兜底」（`_cos_upload(prefer='auto')`），强烈推荐 `pip install cos-python-sdk-v5`

## 输出格式

干净 Markdown，无 YAML frontmatter，无 HTML meta 标签。结构：

```markdown
# 标题

> 来源信息

## 一、概览
（结构化数据表格）

## 二、精华内容
（分小节呈现核心信息）

## 三、参考资料
（所有来源链接）
```

## 安装与使用

### 作为 AI Skill 使用

将此仓库的 `SKILL.md` 安装到你的 AI 编程助手（Claude Code、Codex、Hermes AI 等）：

```bash
npx skills add Wahero/url-extract
```

### 作为独立脚本使用

**Python 依赖**（3 个必需 + 3 个可选）：

```bash
# 必需
pip install requests beautifulsoup4 jinja2

# 可选（强烈推荐）
pip install tenacity           # 重试（B站风控 + IMA API）
pip install cos-python-sdk-v5  # IMA COS 上传 SDK 优先
pip install yt-dlp              # YouTube 元数据 + 字幕

# 全部装
pip install -r requirements.txt
```

**Node.js 依赖**（1 个可选但推荐）：

```bash
npm i -g defuddle  # 一般网页提取（脚本也支持自动探测 npx）
```

**运行**：

```bash
python3 extract.py "https://b23.tv/xxx" -o result.json
```

### IMA 凭证获取

1. 打开 <https://ima.qq.com/agent-interface>
2. 微信扫码登录
3. 页面显示 **Client ID**（自动生成）
4. 点击「获取 API Key」按钮生成 **API Key**（与 Client ID 不同）
5. 设置环境变量：
   ```bash
   export IMA_OPENAPI_CLIENTID="你的ClientID"
   export IMA_OPENAPI_APIKEY="你的APIKey"
   ```

> **安全说明**：本项目不会将凭证写入任何文件。凭证仅通过环境变量在运行时传递，重启后需重新设置。

## 使用场景

- 🌙 **深夜阅读**：把 B 站视频变成文字精华，躺着看
- 📺 **YouTube 摘要**：用 yt-dlp 拿完整字幕 + 元数据（view / like / duration / upload_date）
- 📊 **小红书 / 抖音 调研**：拿到 item_id 后 WebSearch 补内容
- 🔍 **仓库调研**：快速了解一个 GitHub 项目是做什么的
- 📰 **新闻聚合**：把多篇文章链接批量转为精华摘要

## 项目结构

```
url-extract/
├── extract.py                # 主入口脚本（v2.5.2：7 来源 + B站风控 + lazy init + 类型注解）
├── ima_client.py             # IMA OpenAPI 客户端 v1.4（tenacity 重试 + 类型注解 + ETag 判定）
├── setup.py                  # IMA 凭证引导（交互式）
├── SKILL.md                  # AI Skill 定义（7 来源 + 触发词）
├── README.md                 # 本文件
├── CHANGELOG.md              # 完整版本历史
├── REFACTOR_PROGRESS.md      # 2026-08-07 重构工作汇报
├── LICENSE                   # MIT
├── pyproject.toml            # Python 包元数据
├── requirements.txt          # 依赖清单（含可选）
├── templates/                # Markdown 模板（Jinja2，7 个）
│   ├── bilibili.md.j2
│   ├── github.md.j2
│   ├── webpage.md.j2
│   ├── weishi.md.j2
│   ├── youtube.md.j2
│   ├── xiaohongshu.md.j2
│   └── douyin.md.j2
├── tests/                    # 130 个单元测试
│   ├── test_bilibili_cookie_retry.py   (24 用例)
│   ├── test_new_sources.py             (32 用例)
│   ├── test_ima_client.py              (7 用例)
│   ├── test_ima_retry.py               (22 用例)
│   ├── test_cos_sdk_etag.py            (6 用例)
│   ├── test_url_validation.py          (17 用例)
│   ├── test_refactor_13.py             (12 用例)
│   ├── test_templates.py               (10 用例)
│   └── fixtures/           # 测试固定数据
└── .github/workflows/test.yml   # GitHub Actions CI（pytest 3.10/3.11/3.12）
```

## 测试与 CI

- **130 个测试**覆盖：B站风控 / 新来源 / IMA 重试 / COS SDK ETag / URL 验证 / 模板渲染 / 集成
- **CI**: GitHub Actions 跑 pytest 矩阵（Python 3.10 / 3.11 / 3.12）
- **本地跑测试**：
  ```bash
  pip install -r requirements.txt
  python3 -m pytest tests/ -v
  ```

## 关键 CLI 参数速查

```bash
# 来源相关
python3 extract.py <URL> -o result.json

# B 站风控（生产推荐）
python3 extract.py "https://b23.tv/xxx" --sessdata "$BILIBILI_SESSDATA" --wbi-sign on

# IMA 上传
python3 extract.py <URL> --ima-raw                                    # 上传 Markdown 到 RAW
python3 extract.py <URL> --ima-raw --ima-raw-md ./精华.md             # 外部 Markdown 优先
python3 extract.py <URL> --upload-ima --ima-kb "我的知识库"            # URL 导入指定知识库

# IMA API 调优
export IMA_API_RETRY=3               # IMA API 重试次数（默认 3）
export IMA_API_BACKOFF=1             # 基础退避秒数（默认 1）
```

## 已知限制（v2.5.2）

- **小红书 / 抖音**：无登录态拿不到正文，只能拿到 item_id/video_id + 元信息（标记 partial=True）
- **YouTube 字幕**：依赖 yt-dlp 自动生成的 zh-Hans 字幕，无字幕时无降级
- **沙箱网络**：YouTube 沙箱网络常不可达，yt-dlp 会失败，自动降级到 noembed.com（仅 title/author/thumbnail）
- **IMA 业务层错误**：当前 tenacity 只在 api_call 层重试，业务层（find_kb_by_name 等）的双 API 调用还没合并（**待优化**）

## 贡献

欢迎贡献新的来源类型支持、更好的降级策略、或任何改进。

## License

MIT
