"""积木（Maximo 底层）ERP 只读接入包。

数据通道：直连 ERP MySQL（172.20.0.114:3306/php_saas），全部为只读 SELECT。
表映射与口径见《需求对比与改造方案.md》附录 B。
"""

from app.erp.client import ErpClient, ErpQueryError
from app.erp.service import ErpAnalysisService

__all__ = ["ErpClient", "ErpQueryError", "ErpAnalysisService"]
