"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import audit_lineage, resource, chains

# audit_lineage 为固定路径，必须排在动态 /api/{module} 资源路由之前注册。
ROUTERS = [audit_lineage, resource, chains]
