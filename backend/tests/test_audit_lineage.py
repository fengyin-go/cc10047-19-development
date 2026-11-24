"""数据审计-证据版本血缘复核端到端测试。

覆盖题述完整剧本：
先领 e-301 → 再登记 e-304 → 刷新工单和关系详情 → 提交原工单并重新查询两次，
核对两版证据、实际复核项和未处理关系；并验证并发领取幂等、签核冻结、
证据替换与断线恢复不把同页其他关系重新送审。
"""
from __future__ import annotations

import sys
import threading

import pytest

sys.path.insert(0, '.')

from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.services.audit_lineage import (
    CATEGORY_CURRENT,
    CATEGORY_ORIGINAL,
    CATEGORY_UNAFFECTED,
)
from app.store import store

client = TestClient(app)

BATCH = "BATCH-20261120-A"


@pytest.fixture(autouse=True)
def reset_in_memory_store():
    """每个用例从种子数据重新开始，避免共享内存仓库造成用例顺序依赖。"""
    store._tables = {
        name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
    }
    yield


class TestRelationQuery:
    def test_filter_by_batch_column_and_evidence_version(self):
        resp = client.get(
            "/api/audit-lineage/relations",
            params={"扫描批次": BATCH, "下游列": "balance", "证据版本": "v1.0"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        relation = data["items"][0]
        assert relation["关系标识"] == "r-501"
        assert relation["下游列"] == "balance"
        assert relation["当前证据标识"] == "e-301"

    def test_evidence_version_filter_isolates_versions(self):
        resp = client.get(
            "/api/audit-lineage/relations",
            params={"扫描批次": BATCH, "下游列": "balance", "证据版本": "v9.9"},
        )
        assert resp.json()["total"] == 0

    def test_relation_detail_shows_evidence_and_same_page(self):
        resp = client.get("/api/audit-lineage/relations/1")
        detail = resp.json()
        assert detail["当前证据"]["证据标识"] == "e-301"
        assert detail["原证据"] is None
        # 同页（同批次同下游表）其他关系列入未受影响项
        assert {item["关系标识"] for item in detail["未受影响项"]} == {"r-502", "r-504"}
        assert detail["待办"] == ["无待办，按当前采用证据维持审计结论"]


class TestClaimScenario:
    def setup_method(self):
        # 每个测试类内用独立工单，避免与其他类的状态串扰
        self.claim = client.post(
            "/api/audit-lineage/scopes/claim",
            json={"扫描批次": BATCH, "下游列": "balance", "证据版本": "v1.0",
                  "证据标识": "e-301", "领取人": "操作员甲"},
        )

    def test_claim_creates_scope_with_snapshot_items(self):
        assert self.claim.status_code == 200
        data = self.claim.json()
        assert data["ok"] is True and data["reused"] is False
        scope = data["scope"]
        assert scope["工单状态"] == "待复核"
        assert scope["范围关系数"] == 1
        item = scope["复核项"][0]
        assert item["关系标识"] == "r-501"
        assert item["原证据标识"] == "e-301"
        assert item["当前证据标识"] == "e-301"
        # 字段血缘用查到的路径初始化复核范围
        assert item["血缘路径"][-1] == "dwd.acct_wide.balance"

    def test_concurrent_claim_same_scope_one_work_order(self):
        results: list[dict] = []

        def claim() -> None:
            resp = client.post(
                "/api/audit-lineage/scopes/claim",
                json={"扫描批次": BATCH, "下游列": "balance", "证据版本": "v1.0",
                      "证据标识": "e-301", "领取人": "操作员乙"},
            )
            results.append(resp.json())

        threads = [threading.Thread(target=claim) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        scope_codes = {payload["scope"]["工单标识"] for payload in results}
        assert scope_codes == {self.claim.json()["scope"]["工单标识"]}
        assert all(payload["reused"] is True for payload in results)
        # 全局只存在一份该指纹的待复核工单
        scopes = client.get("/api/audit-lineage/scopes").json()["items"]
        matching = [s for s in scopes if s["扫描批次"] == BATCH and s["下游列"] == "balance"]
        assert len(matching) == 1

    def test_claim_empty_scope_rejected(self):
        resp = client.post(
            "/api/audit-lineage/scopes/claim",
            json={"扫描批次": BATCH, "下游列": "not-exist"},
        )
        assert resp.status_code == 400


class TestEvidenceReplacementScenario:
    """完整剧本：先领 e-301，再登记 e-304，刷新工单与详情，提交工单，两次重查。"""

    def test_full_e301_to_e304_scenario(self):
        # 1) 先领 e-301
        claim = client.post(
            "/api/audit-lineage/scopes/claim",
            json={"扫描批次": BATCH, "下游列": "balance", "证据版本": "v1.0",
                  "证据标识": "e-301", "领取人": "操作员甲"},
        ).json()
        scope_id = claim["scope"]["id"]
        scope_code = claim["scope"]["工单标识"]

        # 2) 签核之前登记更正证据 e-304
        register = client.post(
            "/api/audit-lineage/evidence",
            json={"values": {
                "证据标识": "e-304", "扫描批次": BATCH, "来源系统": "ods_cdc_replay",
                "证据版本": "v2.0", "证据说明": "余额来源证据更正版", "登记人": "操作员甲",
            }},
        )
        assert register.status_code == 200
        assert register.json()["entry"]["证据版本"] == "v2.0"

        # 3) 执行证据替换
        replace = client.post(
            "/api/audit-lineage/evidence/replace",
            json={"原证据标识": "e-301", "新证据标识": "e-304"},
        ).json()
        assert replace["ok"] is True
        assert replace["更新关系数"] == 1
        assert replace["更新复核项数"] == 1
        # 同页其他关系（r-502、r-504）不重新送审
        assert set(replace["同页未受影响关系"]) == {"r-502", "r-504"}

        # 4) 刷新工单：复核项记录两版证据，冲突待办可见
        scope = client.get(f"/api/audit-lineage/scopes/{scope_id}").json()
        item = scope["复核项"][0]
        assert item["原证据标识"] == "e-301"
        assert item["当前证据标识"] == "e-304"
        assert item["当前证据版本"] == "v2.0"
        assert item["证据冲突"] is True
        assert item["证据分类"] == CATEGORY_CURRENT

        # 5) 刷新关系详情：标出当前采用证据与后续待办
        detail = client.get("/api/audit-lineage/relations/1").json()
        assert detail["当前证据"]["证据标识"] == "e-304"
        assert detail["原证据"]["证据标识"] == "e-301"
        assert any("e-304" in todo for todo in detail["待办"])
        assert {x["关系标识"] for x in detail["未受影响项"]} == {"r-502", "r-504"}

        # 6) 提交原工单，复核结论回写审计清单
        sign = client.post(
            f"/api/audit-lineage/scopes/{scope_id}/sign-off",
            json={"复核结论": "按更正后证据 e-304 复核通过", "复核人": "审计员"},
        ).json()
        assert sign["ok"] is True
        assert sign["scope"]["工单状态"] == "已签核"

        # 7) 第一次重新查询：清单归入当前证据，复核记录仍在原工单下
        first = client.get(
            "/api/audit-lineage/checklist",
            params={"扫描批次": BATCH, "下游列": "balance"},
        ).json()
        rows = first["items"]
        assert len(rows) == 1
        row = rows[0]
        assert row["工单标识"] == scope_code
        assert row["证据分类"] == CATEGORY_CURRENT
        assert row["当前证据标识"] == "e-304"
        assert row["复核结论"] == "按更正后证据 e-304 复核通过"

        # 8) 第二次重新查询：关系侧待办已回写，未处理关系保持未领取
        detail2 = client.get("/api/audit-lineage/relations/1").json()
        assert "已签核" in detail2["relation"]["待办说明"]
        full = client.get("/api/audit-lineage/checklist", params={"扫描批次": BATCH}).json()
        statuses = {(row["关系标识"], row["证据分类"], row["复核状态"]) for row in full["items"]}
        assert ("r-501", CATEGORY_CURRENT, "已签核") in statuses
        assert ("r-502", CATEGORY_UNAFFECTED, "未领取") in statuses
        assert ("r-503", CATEGORY_UNAFFECTED, "未领取") in statuses
        assert full["groups"][CATEGORY_UNAFFECTED] == 3


class TestSignedItemFreeze:
    def test_replace_after_signoff_keeps_original_evidence(self):
        # 先签核一个工单，再发生证据替换，已签核项必须保留原证据
        claim = client.post(
            "/api/audit-lineage/scopes/claim",
            json={"扫描批次": BATCH, "下游列": "acct_no", "证据版本": "v1.0",
                  "证据标识": "e-302", "领取人": "操作员甲"},
        ).json()
        scope_id = claim["scope"]["id"]
        client.post(
            f"/api/audit-lineage/scopes/{scope_id}/sign-off",
            json={"复核结论": "按 e-302 签核", "复核人": "审计员"},
        )
        client.post(
            "/api/audit-lineage/evidence",
            json={"values": {"证据标识": "e-306", "扫描批次": BATCH,
                             "证据版本": "v2.0", "来源系统": "ods_cdc_replay"}},
        )
        result = client.post(
            "/api/audit-lineage/evidence/replace",
            json={"原证据标识": "e-302", "新证据标识": "e-306"},
        ).json()
        assert result["更新复核项数"] == 0
        assert result["冻结签核项数"] == 1

        item = client.get(f"/api/audit-lineage/scopes/{scope_id}").json()["复核项"][0]
        assert item["当前证据标识"] == "e-302"
        assert item["证据冻结"] is True
        assert item["证据分类"] == CATEGORY_ORIGINAL

        checklist = client.get(
            "/api/audit-lineage/checklist",
            params={"扫描批次": BATCH, "下游列": "acct_no"},
        ).json()
        assert checklist["groups"][CATEGORY_ORIGINAL] == 1


class TestBrokenLineRestore:
    def test_restore_does_not_resubmit_other_relations(self):
        before_checklist = client.get("/api/audit-lineage/checklist",
                                      params={"扫描批次": BATCH}).json()["total"]
        before_scopes = client.get("/api/audit-lineage/scopes").json()["total"]
        resp = client.post("/api/audit-lineage/relations/4/restore").json()
        assert resp["ok"] is True
        assert resp["relation"]["status"] == "正常"
        # 恢复没有新增工单，清单行数（含未领取的未受影响项）保持不变
        assert resp["工单总数"] == before_scopes
        assert client.get("/api/audit-lineage/checklist",
                          params={"扫描批次": BATCH}).json()["total"] == before_checklist
        assert client.get("/api/audit-lineage/scopes").json()["total"] == before_scopes

    def test_mark_broken_then_restore(self):
        client.post("/api/audit-lineage/relations/4/broken")
        broken = client.get("/api/audit-lineage/relations/4").json()["relation"]
        assert broken["status"] == "已断裂"
        restored = client.post("/api/audit-lineage/relations/4/restore").json()
        assert restored["relation"]["status"] == "正常"


class TestEvidenceRegistry:
    def test_duplicate_evidence_rejected(self):
        resp = client.post(
            "/api/audit-lineage/evidence",
            json={"values": {"证据标识": "e-301", "扫描批次": BATCH, "证据版本": "v1.0"}},
        )
        assert resp.status_code == 400

    def test_missing_required_fields(self):
        resp = client.post("/api/audit-lineage/evidence", json={"values": {"证据标识": "e-999"}})
        assert resp.status_code == 400

    def test_unknown_evidence_replace_rejected(self):
        resp = client.post(
            "/api/audit-lineage/evidence/replace",
            json={"原证据标识": "e-301", "新证据标识": "e-not-exist"},
        )
        assert resp.status_code == 400
