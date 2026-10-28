"""url-extract — 通用內容精華抽取。

實作位於子模組：

- ``url_extract.extract``   主流程與各平台抽取
- ``url_extract.ima_client`` IMA 知識庫 OpenAPI 客戶端
- ``url_extract.xhs_asr``   小紅書影片 ASR（可插拔 backend）
- ``url_extract.templates`` Markdown 模板（打包時隨套件附帶）
"""

__all__ = ["extract", "ima_client", "xhs_asr"]
