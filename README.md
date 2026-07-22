# URL Extract — 通用内容精华抽取

> 把视频、网页、GitHub 仓库变回纯粹的精华文字。夜深了不想看视频？信息过载只需要干货？这就是为你准备的。**v2.4：IMA 凭证改为环境变量传递，不持久化存储；--ima-raw 上传完整 Markdown 文档到知识库。**

## 为什么需要它？

外面太多资源——B站视频、小红书笔记、GitHub 仓库、微信公众号链接——混杂着大量无关痛痒的信息。有时候深夜躺在床上不适合看视频，有时候只想快速了解一个仓库做了什么，有时候被标题吸引进去却发现全是废话。

**URL Extract 做的就是一件事：把任何链接变成一篇干净、结构化的精华文章。**

## 支持来源

| 来源 | 示例 | 处理方式 |
|---|---|---|
| **B站视频** | `https://b23.tv/xxx` | 调用 B 站公开 API 获取元信息/字幕/评论 |
| **GitHub 仓库** | `https://github.com/user/repo` | 调用 gh CLI / REST API / 页面抓取三级降级 |
| **腾讯微视** | `https://ugg.weishi.qq.com/...` | 微信 UA 模拟 + 公开报道搜索补充 |
| **一般网页** | 小红书、博客、新闻等 | defuddle 本地提取 |

## 核心设计：多级降级

不依赖单一数据源。当首选方式不可用时，自动降级：

```
B站：字幕 API → 社区文章搜索
GitHub：gh CLI → REST API → 网页抓取
微视：微信 UA 模拟 → 公开报道搜索
网页：defuddle 提取 → meta 提取
```

## IMA 知识库集成（v2.2+）

抽取完成后可一键导入 IMA 知识库。**凭证通过环境变量传递，不写入文件、不持久化存储。**

```bash
# 1. 设置凭证（每次会话需重新设置）
export IMA_OPENAPI_CLIENTID="你的ClientID"
export IMA_OPENAPI_APIKEY="你的APIKey"

# 2. 抽取 + 上传 Markdown 到 RAW 知识库
python3 extract.py "https://example.com/article" --output result.json --ima-raw

# 3. 或导入到指定知识库（URL 导入）
python3 extract.py "https://example.com/article" --output result.json --upload-ima --ima-kb "我的知识库"

# 4. 或仅抽取（不导入 IMA）
python3 extract.py "https://b23.tv/xxx" --output result.json
```

### `--ima-raw` 与 `--upload-ima` 的区别

| 参数 | 导入方式 | 内容 |
|---|---|---|
| `--ima-raw` | 上传 Markdown 文件（四步流程：create_media → COS → add_knowledge） | 完整精华 Markdown 文档 |
| `--upload-ima` | URL 导入（import_urls） | 原始网址链接 |

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

```bash
# 依赖：Python 3.11+, requests, beautifulsoup4
pip install requests beautifulsoup4

# 运行
python3 extract.py "https://b23.tv/xxx" -o result.json
```

### IMA 凭证获取

1. 打开 https://ima.qq.com/agent-interface
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
- 📊 **信息降噪**：从小红书/微博链接中提取干货，去掉废话
- 🔍 **仓库调研**：快速了解一个 GitHub 项目是做什么的
- 📰 **新闻聚合**：把多篇文章链接批量转为精华摘要

## 项目结构

```
url-extract/
├── SKILL.md          # AI Skill 定义（通用版，平台无关）
├── extract.py        # 核心抽取脚本（v2.4：+Markdown上传IMA）
├── ima_client.py     # IMA OpenAPI Python 客户端 v1.2（仅环境变量认证）
├── setup.py          # 凭证引导配置脚本（不持久化）
├── README.md         # 项目说明
└── LICENSE           # MIT License
```

## 贡献

欢迎贡献新的来源类型支持、更好的降级策略、或任何改进。

## License

MIT
