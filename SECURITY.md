# Security Policy

> 安全政策（中英文）

## 支持版本 / Supported Versions

| 版本 Version | 安全更新 Security Fixes |
| --- | --- |
| 2.6.x (最新 latest) | ✅ 支持 Supported |
| < 2.6 | ❌ 不再维护 No longer maintained |

## 报告漏洞 / Reporting a Vulnerability

请通过以下渠道私密报告安全问题，**请勿在公开 Issue 中披露漏洞细节**：

Please report security issues privately via the channels below. **Do not disclose
vulnerability details in public Issues.**

- **GitHub Security Advisory（推荐）**：在仓库 `Wahero/url-extract` 点击
  *Security → Report a vulnerability*。
- **Email**：[填写你的安全联系邮箱，例如 security@example.com]

报告后我们会在 **72 小时内**确认收到，并在 **7 个工作日内**给出初步评估与修复时间表。

We will acknowledge receipt within **72 hours** and provide a preliminary
assessment / remediation timeline within **7 business days**.

## 已知安全边界 / Known Security Boundaries

本项目是一个**本地内容抽取工具**，安全模型依赖「用户在自己机器上、对自己有权使用的链接执行抽取」：

This project is a **local content-extraction tool**. Its security model assumes
the user runs extraction on their own machine, against links they are authorized
to access.

- **SSRF 防护**：`extract()` 与 `validate_url()` 会拒绝访问私网 / 回环 / 链路本地地址
  （含 `127.0.0.1`、`169.254.169.254` 云元数据、私网网段、IP 字面量绕过写法、
  DNS 指向内网、以及 `30x` 重定向跳转到内网）。但仍建议**不要**将本工具直接暴露为公网服务。
- **凭证**：所有第三方凭证（IMA OpenAPI 等）仅从环境变量读取，不持久化到磁盘。
- **依赖**：运行时不自动安装任何包；缺失的可选依赖（yt-dlp / openai-whisper / defuddle）
  需用户手动安装。

- **SSRF protection**: `extract()` and `validate_url()` reject requests to private /
  loopback / link-local addresses (including `127.0.0.1`, `169.254.169.254`
  cloud metadata, private CIDRs, IP-literal bypass forms, DNS-to-internal, and
  `30x` redirect-to-internal). We still recommend **not** exposing this tool as a
  public network service.
- **Credentials**: all third-party credentials (IMA OpenAPI, etc.) are read from
  environment variables only and never persisted to disk.
- **Dependencies**: the tool never auto-installs packages at runtime; missing
  optional deps (yt-dlp / openai-whisper / defuddle) must be installed manually.

## 免责声明 / Disclaimer

本项目按「现状」提供，不对因使用本项目下载、转写或再分发第三方内容所引发的
著作权或平台条款责任提供担保。使用者须自行确保其对该等内容拥有合法使用权限。

Provided "as is", without warranty. We are not liable for any copyright or
platform-terms violations arising from downloading, transcribing, or redistributing
third-party content. Users are responsible for ensuring they have the legal right
to use the source content.
