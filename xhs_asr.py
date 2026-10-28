"""向後相容入口：實作已移至 :mod:`url_extract.xhs_asr`。

新程式碼建議直接匯入 ``url_extract.xhs_asr``。
"""

import sys as _sys

from url_extract import xhs_asr as _impl

_sys.modules[__name__] = _impl
