"""V12.1.1 Patch Proposal 契约和确定性校验测试；不调用模型。"""

import json
import unittest
from pathlib import Path

from models import DiagnosticClaim, Evidence, IncidentReport, PatchProposalDraft
from patching import (
    build_patch_output_contract,
    parse_patch_draft,
    validate_patch_draft,
)


ROOT = Path(__file__).resolve().parent
VALID_DIFF = '''diff --git a/demo_app/app/api.py b/demo_app/app/api.py
--- a/demo_app/app/api.py
+++ b/demo_app/app/api.py
@@ -8,3 +8,5 @@
 def post_users(payload: dict, connection: sqlite3.Connection) -> dict:
+    if "user_id" not in payload:
+        return {"status": 400, "error": "missing user_id"}
     create_user(payload, connection)
     return {"status": 201}'''


def report() -> IncidentReport:
    return IncidentReport(
        summary="缺少输入校验",
        root_cause="API 将未验证 payload 传给 Service",
        claims=[DiagnosticClaim(
            claim_id="C1",
            statement="API 没有检查 user_id",
            evidence_ids=["E1"],
        )],
        evidence=[Evidence(
            evidence_id="E1",
            observation_id="obs-001",
            source_type="code",
            file="demo_app/app/api.py",
            line_start=8,
            line_end=10,
            commit_hash=None,
            runtime_id=None,
            description="API 直接调用 Service",
        )],
        suggested_fixes=["增加必填字段校验"],
        confidence="high",
    )


def draft(**updates) -> PatchProposalDraft:
    values = {
        "diagnosis_claim_ids": ["C1"],
        "changed_files": ["demo_app/app/api.py"],
        "unified_diff": VALID_DIFF,
        "rationale": "在 API 边界拒绝缺失字段",
        "risks": ["需要确认使用 400 还是 422"],
        "verification_check_ids": ["demo_smoke_suite"],
    }
    values.update(updates)
    return PatchProposalDraft.model_validate(values)


class PatchProposalTests(unittest.TestCase):
    def test_output_contract_exposes_exact_fields_and_registered_checks(self) -> None:
        contract = build_patch_output_contract()

        for field in PatchProposalDraft.model_fields:
            self.assertIn(field, contract)
        self.assertIn("demo_missing_user_id", contract)
        self.assertIn("不得添加 type、patch_id、status", contract)

    def test_valid_patch_is_accepted_without_changing_source_file(self) -> None:
        path = ROOT / "demo_app/app/api.py"
        before = path.read_bytes()

        proposal = validate_patch_draft(draft(), report())

        self.assertEqual(proposal.status, "validated")
        self.assertEqual(proposal.validation_errors, [])
        self.assertTrue(proposal.proposal_id.startswith("patch-"))
        self.assertEqual(path.read_bytes(), before)

    def test_context_that_does_not_match_current_file_is_rejected(self) -> None:
        proposal = validate_patch_draft(
            draft(unified_diff=VALID_DIFF.replace(
                "create_user(payload, connection)",
                "create_user(other_payload, connection)",
            )),
            report(),
        )

        self.assertEqual(proposal.status, "rejected")
        self.assertTrue(any("上下文与当前文件不一致" in item
                            for item in proposal.validation_errors))

    def test_patch_cannot_modify_file_missing_from_code_evidence(self) -> None:
        changed = VALID_DIFF.replace("demo_app/app/api.py", "demo_app/app/service.py")
        changed = changed.replace(
            "def post_users(payload: dict, connection: sqlite3.Connection) -> dict:\n"
            "+    if \"user_id\" not in payload:\n"
            "+        return {\"status\": 400, \"error\": \"missing user_id\"}\n"
            "     create_user(payload, connection)\n"
            "     return {\"status\": 201}",
            "def create_user(payload: dict, connection: sqlite3.Connection) -> None:\n"
            "+    if \"user_id\" not in payload:\n"
            "+        raise ValueError(\"missing user_id\")\n"
            "     # BUG-001：默认 API 层已经校验，但 api.py 实际没有校验。\n"
            "     user_id = payload[\"user_id\"]",
        ).replace("@@ -8,3 +8,5 @@", "@@ -8,3 +8,5 @@")
        proposal = validate_patch_draft(
            draft(
                changed_files=["demo_app/app/service.py"],
                unified_diff=changed,
            ),
            report(),
        )

        self.assertEqual(proposal.status, "rejected")
        self.assertTrue(any("没有出现在诊断代码 Evidence" in item
                            for item in proposal.validation_errors))

    def test_unknown_claim_and_harness_check_are_rejected(self) -> None:
        proposal = validate_patch_draft(
            draft(
                diagnosis_claim_ids=["C404"],
                verification_check_ids=["not_registered"],
            ),
            report(),
        )

        self.assertEqual(proposal.status, "rejected")
        self.assertTrue(any("Claim 不存在" in item
                            for item in proposal.validation_errors))
        self.assertTrue(any("Harness 中登记" in item
                            for item in proposal.validation_errors))

    def test_test_and_harness_files_are_protected(self) -> None:
        unsafe = VALID_DIFF.replace("demo_app/app/api.py", "test_graph.py")
        proposal = validate_patch_draft(
            draft(changed_files=["test_graph.py"], unified_diff=unsafe),
            report(),
        )

        self.assertEqual(proposal.status, "rejected")
        self.assertTrue(any("受保护文件" in item
                            for item in proposal.validation_errors))

    def test_patch_cannot_change_file_mode(self) -> None:
        mode_change = VALID_DIFF.replace(
            "--- a/demo_app/app/api.py",
            "old mode 100644\nnew mode 100755\n--- a/demo_app/app/api.py",
        )

        proposal = validate_patch_draft(
            draft(unified_diff=mode_change),
            report(),
        )

        self.assertEqual(proposal.status, "rejected")
        self.assertTrue(any("改权限" in item
                            for item in proposal.validation_errors))

    def test_markdown_json_fence_is_parsed(self) -> None:
        payload = json.dumps(draft().model_dump())
        parsed = parse_patch_draft(f"```json\n{payload}\n```")

        self.assertEqual(parsed.changed_files, ["demo_app/app/api.py"])


if __name__ == "__main__":
    unittest.main()
