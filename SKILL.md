---
name: url-extract
description: 把链接（B站视频 / GitHub 仓库 / 一般网页 / 腾讯微视）变成结构化 Markdown 精华文档，可选上传到 IMA 知识库。触发词：精华、总结、提取、生成精华、B站精华、GitHub总结、网页精华。
allowed-tools: Read, Write, Bash, WebSearch
---

# URL Extract — 通用内容精华抽取

把任何链接变成一篇干净、结构化的 Markdown 精华文档。支持：B 站视频、GitHub 仓库、一般网页、腾讯微视。**`--ima-raw` 上传完整 Markdown 到 IMA「RAW」知识库；`--ima-raw-md` 支持外部 Markdown 文件优先上传。**

> ⚠️ **学术测试版（Academic Preview）** — 当视频无字幕时，部分要点来自社区资料整合而非视频原声。正式参考请对照原始视频核实。

## 零配置快速上手

```bash
# 1. 安装依赖
pip install -r requirements.txt        # Python
npm i -g defuddle                      # 可选：自动安装也可

# 2. 抽取任意链接 → 输出 JSON
python3 extract.py "https://b23.tv/xxx" --output result.json

# 3. 一键上传到 IMA（可选，需先 export 凭证）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"
python3 extract.py "https://b23.tv/xxx" --output result.json --ima-raw
```

## 支持来源

| 来源 | 检测规则 | 抽取方式 |
|---|---|---|
| **B站视频** | `bilibili.com` / `b23.tv` / `BV号` | 公共 API（视频信息/标签/字幕/评论） |
| **GitHub 仓库** | `github.com` | gh CLI → REST API → defuddle 三级降级 |
| **腾讯微视** | `weishi.qq.com` / 微信插件链接 | 微信 UA 模拟 + WebSearch 补充 |
| **一般网页** | 以上都不是 | defuddle CLI 一步提取 |

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

### IMA 模块文件

| 文件 | 说明 |
|---|---|
| `ima_client.py` | IMA OpenAPI 客户端，仅环境变量认证 |
| `setup.py` | 凭证引导脚本，交互式输入 |

所有 IMA 请求仅发往 `https://ima.qq.com`，凭证永不出现在代码中。

---

## 依赖

- **Python 3.10+** + `requests` + `beautifulsoup4` + `jinja2`（见 `requirements.txt`）
- **Node.js 18+** + `defuddle`（推荐全局安装：`npm i -g defuddle`；脚本也支持自动探测 `npx defuddle`）

## 项目结构

```
url-extract/
├── SKILL.md                # 本文件
├── README.md               # 项目说明
├── extract.py              # 主入口脚本
├── ima_client.py           # IMA 客户端
├── setup.py                # IMA 凭证引导
├── pyproject.toml          # Python 包元数据
├── requirements.txt        # Python 依赖
├── templates/              # Markdown 模板（Jinja2）
│   ├── bilibili.md.j2
│   ├── github.md.j2
│   ├── webpage.md.j2
│   └── weishi.md.j2
├── tests/                  # 单元测试
└── LICENSE
```

## 版本历史

详见 [CHANGELOG.md](CHANGELOG.md)
