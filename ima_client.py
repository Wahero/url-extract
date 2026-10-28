"""向後相容入口：實作已移至 :mod:`url_extract.ima_client`。

新程式碼建議直接匯入 ``url_extract.ima_client``。
"""

import sys as _sys

from url_extract import ima_client as _impl

if __name__ == "__main__":
    _impl.main()
else:
    _sys.modules[__name__] = _impl
