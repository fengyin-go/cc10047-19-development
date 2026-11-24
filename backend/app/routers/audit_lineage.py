"""数据审计-证据版本血缘复核路由。

在通用资源路由之前注册，固定路径不会被 /api/{module} 动态路由抢占。
所有业务判断都在 AuditLineageService 内，路由层只做参数搬运。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.audit_lineage import service

router = APIRouter(prefix="/api/audit-lineage", tags=["数据审计证据复核"])


class EvidencePayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class ClaimPayload(BaseModel):
    扫描批次: str
    下游列: str
    证据版本: str | None = None
    证据标识: str | None = None
    领取人: str | None = None


class ReplacePayload(BaseModel):
    原证据标识: str
    新证据标识: str


class SignOffPayload(BaseModel):
    复核结论: str
    复核人: str | None = None


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "操作失败"))
    return result


@router.get("/evidence")
def get_evidence(扫描批次: str | None = None) -> dict[str, Any]:
    """证据登记清单，可按扫描批次筛选。"""
    items = service.list_evidence(scan_batch=扫描批次)
    return {"items": items, "total": len(items)}


@router.post("/evidence")
def register_evidence(payload: EvidencePayload) -> dict[str, Any]:
    """登记新证据版本（证据本身不可变，重复证据标识会被拒绝）。"""
    entry, missing = service.register_evidence(payload.values)
    if missing:
        raise HTTPException(status_code=400, detail=f"登记失败：{'、'.join(missing)}")
    return {"ok": True, "message": "证据已登记", "entry": entry}


@router.get("/relations")
def query_relations(
    扫描批次: str | None = None,
    下游列: str | None = None,
    证据版本: str | None = None,
) -> dict[str, Any]:
    """按扫描批次、下游列和证据版本定位字段血缘关系。"""
    items = service.query_relations(
        scan_batch=扫描批次,
        downstream_column=下游列,
        evidence_version=证据版本,
    )
    return {"items": items, "total": len(items)}


@router.get("/relations/{relation_id}")
def get_relation_detail(relation_id: int) -> dict[str, Any]:
    """关系详情：原证据、当前证据、同页未受影响项、复核记录和后续待办。"""
    detail = service.relation_detail(relation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"字段血缘关系 {relation_id} 不存在")
    return detail


@router.post("/scopes/claim")
def claim_scope(payload: ClaimPayload) -> dict[str, Any]:
    """领取受变更影响的审计复核范围；相同范围并发领取只生成一份工单。"""
    return _ok(service.claim_scope(payload.model_dump()))


@router.get("/scopes")
def list_scopes(工单状态: str | None = None) -> dict[str, Any]:
    items = service.list_scopes(scope_status=工单状态)
    return {"items": items, "total": len(items)}


@router.get("/scopes/{scope_id}")
def get_scope(scope_id: int) -> dict[str, Any]:
    detail = service.scope_detail(scope_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"复核工单 {scope_id} 不存在")
    return detail


@router.post("/evidence/replace")
def replace_evidence(payload: ReplacePayload) -> dict[str, Any]:
    """证据替换：未签核复核项同步到新证据，已签核项冻结保留原证据，同页其他关系不送审。"""
    return _ok(service.replace_evidence(payload.model_dump()))


@router.post("/relations/{relation_id}/broken")
def mark_broken(relation_id: int) -> dict[str, Any]:
    return _ok(service.mark_broken(relation_id))


@router.post("/relations/{relation_id}/restore")
def restore_relation(relation_id: int) -> dict[str, Any]:
    """断线恢复：只恢复当前关系，不会把同页其他关系重新送审。"""
    return _ok(service.restore_relation(relation_id))


@router.post("/scopes/{scope_id}/sign-off")
def sign_off_scope(scope_id: int, payload: SignOffPayload) -> dict[str, Any]:
    """提交复核工单：复核结论回写审计清单并冻结复核项。"""
    return _ok(service.sign_off_scope(scope_id, payload.model_dump()))


@router.get("/checklist")
def get_checklist(
    扫描批次: str | None = None,
    下游列: str | None = None,
    工单标识: str | None = None,
) -> dict[str, Any]:
    """审计清单：区分原证据、当前证据及其他未受影响项。"""
    return service.checklist(
        scan_batch=扫描批次,
        downstream_column=下游列,
        scope_code=工单标识,
    )
