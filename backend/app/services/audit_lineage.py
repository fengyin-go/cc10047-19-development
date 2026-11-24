"""数据审计-证据版本血缘复核领域服务。

承载四类数据：
- audit_evidence：证据登记（按扫描批次、证据版本留痕，证据本身不可变）；
- audit_relation：字段血缘关系，带当前采用证据与原证据、血缘路径、替换关系；
- audit_scope：受变更影响的审计复核范围（工单），相同范围并发领取只生成一份；
- audit_review_item：工单下的复核记录，即审计清单行，复核结论回写于此。

关键规则：
1. 关系可按扫描批次、下游列、证据版本筛选定位；
2. 证据替换只更新未签核工单的复核项，已签核项冻结保留原证据；
3. 证据替换、断线恢复均不会把同页（同批次同下游表）其他关系重新送审；
4. 清单/详情按 原证据 / 当前证据 / 未受影响 三分类展示。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

# 复核项证据三分类
CATEGORY_ORIGINAL = "原证据"        # 已签核后证据才被替换，冻结保留原证据
CATEGORY_CURRENT = "当前证据"       # 未签核复核项跟随到了替换后的新证据
CATEGORY_UNAFFECTED = "未受影响"    # 证据从未发生替换

SCOPE_OPEN = "待复核"
SCOPE_SIGNED = "已签核"
ITEM_OPEN = "待复核"
ITEM_SIGNED = "已签核"
RELATION_NORMAL = "正常"
RELATION_BROKEN = "已断裂"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_id(table: str) -> int:
    rows = store.rows(table)
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


class AuditLineageService:
    """证据版本血缘复核的全部领域逻辑；服务为单例，自带领取锁保证工单幂等。"""

    def __init__(self) -> None:
        self._claim_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 证据登记
    # ------------------------------------------------------------------
    def list_evidence(self, scan_batch: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("audit_evidence")
        if scan_batch:
            rows = [row for row in rows if row.get("扫描批次") == scan_batch]
        return [dict(row) for row in rows]

    def get_evidence(self, evidence_code: str) -> dict[str, Any] | None:
        for row in store.rows("audit_evidence"):
            if row.get("证据标识") == evidence_code:
                return row
        return None

    def register_evidence(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        required = ["证据标识", "扫描批次", "证据版本"]
        missing = [field for field in required if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        code = str(values["证据标识"]).strip()
        if self.get_evidence(code) is not None:
            return None, [f"证据标识 {code} 已登记，不能重复登记"]
        entry: dict[str, Any] = {
            "id": _next_id("audit_evidence"),
            "status": "有效",
            "pending": False,
            "abnormal": False,
            "证据标识": code,
            "扫描批次": str(values["扫描批次"]).strip(),
            "来源系统": str(values.get("来源系统") or "").strip(),
            "证据版本": str(values["证据版本"]).strip(),
            "证据说明": str(values.get("证据说明") or "").strip(),
            "登记人": str(values.get("登记人") or "审计值班员").strip(),
            "登记时间": _now(),
        }
        store.rows("audit_evidence").append(entry)
        return dict(entry), []

    # ------------------------------------------------------------------
    # 关系读取与筛选：按扫描批次、下游列、证据版本定位
    # ------------------------------------------------------------------
    def query_relations(
        self,
        *,
        scan_batch: str | None = None,
        downstream_column: str | None = None,
        evidence_version: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = store.rows("audit_relation")
        if scan_batch:
            rows = [row for row in rows if row.get("扫描批次") == scan_batch.strip()]
        if downstream_column:
            key = downstream_column.strip()
            rows = [row for row in rows if row.get("下游列") == key]
        if evidence_version:
            key = evidence_version.strip()
            rows = [row for row in rows if row.get("证据版本") == key]
        return [dict(row) for row in rows]

    def _find_relation(self, relation_id: int) -> dict[str, Any] | None:
        return store.find("audit_relation", relation_id)

    def relation_detail(self, relation_id: int) -> dict[str, Any] | None:
        relation = self._find_relation(relation_id)
        if relation is None:
            return None
        # 同页：同扫描批次、同下游表；排除自身与已发生证据替换的关系，即为未受影响项
        unaffected = [
            dict(row)
            for row in store.rows("audit_relation")
            if row.get("扫描批次") == relation.get("扫描批次")
            and row.get("下游表") == relation.get("下游表")
            and int(row.get("id", 0)) != relation_id
            and not row.get("原证据标识")
        ]
        original_evidence = (
            self.get_evidence(relation["原证据标识"]) if relation.get("原证据标识") else None
        )
        current_evidence = self.get_evidence(relation.get("当前证据标识", ""))
        review_records = [
            dict(item)
            for item in store.rows("audit_review_item")
            if item.get("relation_id") == relation_id
        ]
        for item in review_records:
            item["证据分类"] = self._classify(item)
        todos = self._relation_todos(relation)
        return {
            "relation": dict(relation),
            "原证据": dict(original_evidence) if original_evidence else None,
            "当前证据": dict(current_evidence) if current_evidence else None,
            "未受影响项": unaffected,
            "复核记录": review_records,
            "待办": todos,
        }

    def _relation_todos(self, relation: dict[str, Any]) -> list[str]:
        todos: list[str] = []
        if relation.get("证据冲突"):
            todos.append(
                f"来源证据已由 {relation.get('原证据标识')} 更正为 "
                f"{relation.get('当前证据标识')}，需在复核工单中确认当前采用证据"
            )
        if relation.get("status") == RELATION_BROKEN:
            todos.append("字段血缘已断裂，需修复上游后执行断线恢复")
        if todos:
            return todos
        # 无活跃冲突/断线时，回显最近一次复核或恢复写入的处理说明
        if relation.get("待办说明"):
            return [str(relation["待办说明"])]
        return ["无待办，按当前采用证据维持审计结论"]

    # ------------------------------------------------------------------
    # 领取复核范围：相同范围（批次+下游列+证据）并发只生成一份工单
    # ------------------------------------------------------------------
    def claim_scope(self, payload: dict[str, Any]) -> dict[str, Any]:
        scan_batch = str(payload.get("扫描批次") or "").strip()
        downstream_column = str(payload.get("下游列") or "").strip()
        evidence_version = str(payload.get("证据版本") or "").strip() or None
        evidence_code = str(payload.get("证据标识") or "").strip() or None
        operator = str(payload.get("领取人") or "审计值班员").strip()
        if not scan_batch or not downstream_column:
            return {"ok": False, "message": "领取复核范围必须提供扫描批次和下游列"}

        with self._claim_lock:
            relations = self.query_relations(
                scan_batch=scan_batch,
                downstream_column=downstream_column,
                evidence_version=evidence_version,
            )
            if evidence_code:
                relations = [row for row in relations if row.get("当前证据标识") == evidence_code]
            if not relations:
                return {"ok": False, "message": "按给定扫描批次、下游列和证据版本未定位到字段血缘关系"}

            evidence_codes = sorted({row.get("当前证据标识", "") for row in relations})
            fingerprint = f"{scan_batch}|{downstream_column}|{'|'.join(evidence_codes)}"

            # 幂等：存在同指纹的未签核工单则直接复用，不再生成第二份
            for scope in store.rows("audit_scope"):
                if scope.get("范围指纹") == fingerprint and scope.get("工单状态") == SCOPE_OPEN:
                    return {
                        "ok": True,
                        "reused": True,
                        "message": "相同范围已存在待复核工单，已直接复用，未重复生成工单",
                        "scope": self._scope_detail(scope["id"]),
                    }

            scope_id = _next_id("audit_scope")
            scope_code = f"AR-{scope_id:04d}"
            scope = {
                "id": scope_id,
                "status": SCOPE_OPEN,
                "pending": True,
                "abnormal": False,
                "工单标识": scope_code,
                "扫描批次": scan_batch,
                "下游列": downstream_column,
                "范围指纹": fingerprint,
                "领取人": operator,
                "工单状态": SCOPE_OPEN,
                "领取时间": _now(),
                "签核时间": "",
                "复核结论": "",
                "范围关系数": len(relations),
            }
            store.rows("audit_scope").append(scope)

            items = []
            for relation in relations:
                evidence = self.get_evidence(relation.get("当前证据标识", ""))
                item = {
                    "id": _next_id("audit_review_item"),
                    "status": ITEM_OPEN,
                    "pending": True,
                    "abnormal": False,
                    "scope_id": scope_id,
                    "工单标识": scope_code,
                    "relation_id": relation["id"],
                    "关系标识": relation.get("关系标识"),
                    "扫描批次": relation.get("扫描批次"),
                    "下游表": relation.get("下游表"),
                    "下游列": relation.get("下游列"),
                    "血缘路径": list(relation.get("血缘路径") or []),
                    "替换关系": relation.get("替换关系", ""),
                    "原证据标识": relation.get("当前证据标识", ""),
                    "原证据版本": relation.get("证据版本", ""),
                    "当前证据标识": relation.get("当前证据标识", ""),
                    "当前证据版本": relation.get("证据版本", ""),
                    "证据冲突": False,
                    "证据冻结": False,
                    "复核状态": ITEM_OPEN,
                    "复核结论": "",
                    "复核人": "",
                    "复核时间": "",
                    "证据来源系统": evidence.get("来源系统", "") if evidence else "",
                }
                store.rows("audit_review_item").append(item)
                items.append(item)

            return {
                "ok": True,
                "reused": False,
                "message": f"已领取受变更影响的审计复核范围，生成工单 {scope_code}",
                "scope": self._scope_detail(scope_id),
            }

    def list_scopes(self, scope_status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows("audit_scope")
        if scope_status:
            rows = [row for row in rows if row.get("工单状态") == scope_status.strip()]
        return [dict(row) for row in rows]

    def _classify(self, item: dict[str, Any]) -> str:
        if item.get("证据冻结"):
            # 签核后才发生证据替换：复核项冻结在旧证据上，清单归入原证据
            return CATEGORY_ORIGINAL
        if item.get("原证据标识") != item.get("当前证据标识"):
            # 未签核复核项已跟随替换后的新证据，清单归入当前证据
            return CATEGORY_CURRENT
        return CATEGORY_UNAFFECTED

    def _scope_detail(self, scope_id: int) -> dict[str, Any] | None:
        scope = store.find("audit_scope", scope_id)
        if scope is None:
            return None
        items = [
            dict(item)
            for item in store.rows("audit_review_item")
            if item.get("scope_id") == scope_id
        ]
        for item in items:
            item["证据分类"] = self._classify(item)
        detail = dict(scope)
        detail["复核项"] = items
        return detail

    def scope_detail(self, scope_id: int) -> dict[str, Any] | None:
        return self._scope_detail(scope_id)

    # ------------------------------------------------------------------
    # 证据替换：更新关系路径/替换关系与未签核复核项，签核项保留原证据
    # ------------------------------------------------------------------
    def replace_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        old_code = str(payload.get("原证据标识") or "").strip()
        new_code = str(payload.get("新证据标识") or "").strip()
        if not old_code or not new_code:
            return {"ok": False, "message": "证据替换必须提供原证据标识和新证据标识"}
        if old_code == new_code:
            return {"ok": False, "message": "新证据与原证据相同，无需替换"}
        old_evidence = self.get_evidence(old_code)
        new_evidence = self.get_evidence(new_code)
        if old_evidence is None or new_evidence is None:
            missing = old_code if old_evidence is None else new_code
            return {"ok": False, "message": f"证据 {missing} 未登记，无法执行替换"}

        impacted_relations = [
            row for row in store.rows("audit_relation")
            if row.get("当前证据标识") == old_code
        ]
        if not impacted_relations:
            return {"ok": False, "message": f"当前没有关系采用证据 {old_code}，无需替换"}

        same_page_ids: set[int] = set()
        for relation in impacted_relations:
            for row in store.rows("audit_relation"):
                if (
                    row.get("扫描批次") == relation.get("扫描批次")
                    and row.get("下游表") == relation.get("下游表")
                ):
                    same_page_ids.add(int(row.get("id", 0)))

        updated_relation_ids: list[int] = []
        for relation in impacted_relations:
            relation["原证据标识"] = old_code
            relation["当前证据标识"] = new_code
            relation["证据版本"] = new_evidence.get("证据版本", "")
            relation["证据冲突"] = True
            relation["待办说明"] = (
                f"来源证据已由 {old_code}（{old_evidence.get('证据版本')}）更正为 "
                f"{new_code}（{new_evidence.get('证据版本')}），待审计复核确认当前采用证据"
            )
            relation["替换关系"] = (
                f"证据替换：{old_code} → {new_code}；"
                f"上游路径沿用 {relation.get('上游表', '')}.{relation.get('上游列', '')}"
            )
            relation["更新时间"] = _now()
            updated_relation_ids.append(int(relation["id"]))

        open_updated_items: list[int] = []
        frozen_signed_items: list[int] = []
        for item in store.rows("audit_review_item"):
            if item.get("relation_id") not in updated_relation_ids:
                continue
            if item.get("复核状态") == ITEM_SIGNED:
                # 已签核项冻结：保留原证据，不随替换改写
                item["证据冻结"] = True
                frozen_signed_items.append(int(item["id"]))
                continue
            item["当前证据标识"] = new_code
            item["当前证据版本"] = new_evidence.get("证据版本", "")
            item["证据冲突"] = True
            item["证据来源系统"] = new_evidence.get("来源系统", "")
            relation = self._find_relation(int(item["relation_id"]))
            if relation is not None:
                item["血缘路径"] = list(relation.get("血缘路径") or [])
                item["替换关系"] = relation.get("替换关系", "")
            open_updated_items.append(int(item["id"]))

        # 同页其他关系（不同证据）保持原样，不生成任何新的复核项/工单
        unaffected_same_page = [
            row.get("关系标识")
            for row in store.rows("audit_relation")
            if int(row.get("id", 0)) in same_page_ids
            and int(row.get("id", 0)) not in updated_relation_ids
        ]
        return {
            "ok": True,
            "message": f"证据 {old_code} 已替换为 {new_code}，未签核复核项已同步，签核项保留原证据",
            "原证据标识": old_code,
            "新证据标识": new_code,
            "更新关系数": len(updated_relation_ids),
            "更新复核项数": len(open_updated_items),
            "冻结签核项数": len(frozen_signed_items),
            "同页未受影响关系": unaffected_same_page,
        }

    # ------------------------------------------------------------------
    # 断线 / 恢复：只动当前关系，绝不把同页其他关系重新送审
    # ------------------------------------------------------------------
    def mark_broken(self, relation_id: int) -> dict[str, Any]:
        relation = self._find_relation(relation_id)
        if relation is None:
            return {"ok": False, "message": f"字段血缘关系 {relation_id} 不存在"}
        relation["status"] = RELATION_BROKEN
        relation["pending"] = True
        relation["abnormal"] = True
        relation["待办说明"] = "字段血缘已断裂，需修复上游后执行断线恢复"
        relation["更新时间"] = _now()
        return {"ok": True, "message": f"关系 {relation.get('关系标识')} 已标记断裂", "relation": dict(relation)}

    def restore_relation(self, relation_id: int) -> dict[str, Any]:
        relation = self._find_relation(relation_id)
        if relation is None:
            return {"ok": False, "message": f"字段血缘关系 {relation_id} 不存在"}
        before_items = len(store.rows("audit_review_item"))
        before_scopes = len(store.rows("audit_scope"))
        relation["status"] = RELATION_NORMAL
        relation["pending"] = False
        relation["abnormal"] = False
        if relation.get("证据冲突"):
            relation["待办说明"] = (
                f"断线已恢复；证据替换 {relation.get('原证据标识')} → "
                f"{relation.get('当前证据标识')} 仍待复核确认"
            )
        else:
            relation["待办说明"] = "断线已恢复，沿用当前采用证据"
        relation["更新时间"] = _now()
        after_items = len(store.rows("audit_review_item"))
        after_scopes = len(store.rows("audit_scope"))
        # 硬性不变量：恢复不能新增工单或复核项，同页其他关系不会被重新送审
        assert after_items == before_items and after_scopes == before_scopes
        return {
            "ok": True,
            "message": f"关系 {relation.get('关系标识')} 已断线恢复，同页其他关系未重新送审",
            "relation": dict(relation),
            "复核项总数": after_items,
            "工单总数": after_scopes,
        }

    # ------------------------------------------------------------------
    # 签核：复核结论回写审计清单，复核项冻结
    # ------------------------------------------------------------------
    def sign_off_scope(self, scope_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        scope = store.find("audit_scope", scope_id)
        if scope is None:
            return {"ok": False, "message": f"复核工单 {scope_id} 不存在"}
        if scope.get("工单状态") != SCOPE_OPEN:
            return {"ok": False, "message": f"工单 {scope.get('工单标识')} 已签核，不能重复签核"}
        conclusion = str(payload.get("复核结论") or "").strip()
        reviewer = str(payload.get("复核人") or scope.get("领取人") or "审计值班员").strip()
        if not conclusion:
            return {"ok": False, "message": "签核必须填写复核结论"}

        now = _now()
        scope["工单状态"] = SCOPE_SIGNED
        scope["status"] = SCOPE_SIGNED
        scope["pending"] = False
        scope["签核时间"] = now
        scope["复核结论"] = conclusion
        touched_relations: set[int] = set()
        for item in store.rows("audit_review_item"):
            if item.get("scope_id") != scope_id:
                continue
            item["复核状态"] = ITEM_SIGNED
            item["status"] = ITEM_SIGNED
            item["pending"] = False
            item["证据冻结"] = False
            item["复核结论"] = conclusion
            item["复核人"] = reviewer
            item["复核时间"] = now
            touched_relations.add(int(item.get("relation_id", 0)))

        # 结论回写关系侧待办；证据版本保持复核项冻结时的口径
        for relation_id in touched_relations:
            relation = self._find_relation(relation_id)
            if relation is None:
                continue
            relation["证据冲突"] = False
            relation["待办说明"] = (
                f"工单 {scope.get('工单标识')} 已签核：{conclusion}；"
                f"当前采用证据 {relation.get('当前证据标识')}"
            )
            relation["更新时间"] = now
        return {"ok": True, "message": f"工单 {scope.get('工单标识')} 已签核，结论已回写审计清单",
                "scope": self._scope_detail(scope_id)}

    # ------------------------------------------------------------------
    # 审计清单：原证据 / 当前证据 / 未受影响 三分类
    # ------------------------------------------------------------------
    def checklist(
        self,
        *,
        scan_batch: str | None = None,
        downstream_column: str | None = None,
        scope_code: str | None = None,
    ) -> dict[str, Any]:
        items = list(store.rows("audit_review_item"))
        if scope_code:
            items = [row for row in items if row.get("工单标识") == scope_code.strip()]
        if scan_batch:
            items = [row for row in items if row.get("扫描批次") == scan_batch.strip()]
        if downstream_column:
            items = [row for row in items if row.get("下游列") == downstream_column.strip()]

        rows: list[dict[str, Any]] = []
        covered_relation_ids = {int(row.get("relation_id", 0)) for row in items}
        for item in items:
            row = dict(item)
            row["证据分类"] = self._classify(item)
            rows.append(row)

        # 未受影响：同筛选条件下从未进入任何复核范围的关系，作为清单中的未处理关系呈现
        relations = self.query_relations(
            scan_batch=scan_batch, downstream_column=downstream_column
        )
        for relation in relations:
            if int(relation["id"]) in covered_relation_ids:
                continue
            if scope_code:
                continue
            evidence = self.get_evidence(relation.get("当前证据标识", ""))
            rows.append({
                "id": f"rel-{relation['id']}",
                "relation_id": relation["id"],
                "关系标识": relation.get("关系标识"),
                "工单标识": "",
                "扫描批次": relation.get("扫描批次"),
                "下游表": relation.get("下游表"),
                "下游列": relation.get("下游列"),
                "原证据标识": relation.get("原证据标识") or relation.get("当前证据标识", ""),
                "原证据版本": relation.get("证据版本", ""),
                "当前证据标识": relation.get("当前证据标识", ""),
                "当前证据版本": relation.get("证据版本", ""),
                "证据来源系统": evidence.get("来源系统", "") if evidence else "",
                "证据冻结": False,
                "血缘路径": list(relation.get("血缘路径") or []),
                "复核状态": "未领取",
                "复核结论": "",
                "证据分类": CATEGORY_UNAFFECTED,
                "待办说明": relation.get("待办说明", ""),
            })

        groups = {
            CATEGORY_ORIGINAL: sum(1 for row in rows if row["证据分类"] == CATEGORY_ORIGINAL),
            CATEGORY_CURRENT: sum(1 for row in rows if row["证据分类"] == CATEGORY_CURRENT),
            CATEGORY_UNAFFECTED: sum(1 for row in rows if row["证据分类"] == CATEGORY_UNAFFECTED),
        }
        return {"items": rows, "total": len(rows), "groups": groups}


service = AuditLineageService()
