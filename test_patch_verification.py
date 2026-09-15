"""V13 隔离补丁验证测试；只运行预登记本地检查，不调用模型。"""

import json
import tempfile
import unittest
from pathlib import Path

from models import DiagnosticClaim, Evidence, IncidentReport, PatchProposalDraft
from patch_verification import verify_patch_in_sandbox
from patching import apply_validated_patch_to_sandbox, validate_patch_draft


ROOT = Path(__file__).resolve().parent


def report() -> IncidentReport:
    return IncidentReport(
        summary="API 缺少必填字段校验",
        root_cause="post_users 将未校验 payload 传给 Service",
        claims=[DiagnosticClaim(
            claim_id="C1",
            statement="API 必须在调用 Service 前返回 400",
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
        suggested_fixes=["缺少必填字段时返回 400"],
        confidence="high",
    )


def proposal(return_400: bool):
    response = (
        '        return {"status": 400, "error": "missing required fields: " '
        '+ ", ".join(missing)}'
        if return_400
        else '        raise ValueError(f"missing required fields: {\', \'.join(missing)}")'
    )
    diff = (
        "diff --git a/demo_app/app/api.py b/demo_app/app/api.py\n"
        "--- a/demo_app/app/api.py\n"
        "+++ b/demo_app/app/api.py\n"
        "@@ -8,3 +8,6 @@\n"
        " def post_users(payload: dict, connection: sqlite3.Connection) -> dict:\n"
        "+    missing = [field for field in (\"user_id\", \"email\") if field not in payload]\n"
        "+    if missing:\n"
        f"+{response}\n"
        "     create_user(payload, connection)\n"
        "     return {\"status\": 201}"
    )
    draft = PatchProposalDraft(
        diagnosis_claim_ids=["C1"],
        changed_files=["demo_app/app/api.py"],
        unified_diff=diff,
        rationale="在入口实现文档要求的必填字段校验",
        risks=[],
        verification_check_ids=["demo_missing_user_id"],
    )
    return validate_patch_draft(draft, report())


class PatchVerificationTests(unittest.TestCase):
    def test_contract_compliant_patch_is_verified_without_workspace_change(self):
        candidate = proposal(return_400=True)
        source = ROOT / "demo_app/app/api.py"
        before = source.read_bytes()

        result = verify_patch_in_sandbox(
            candidate,
            report(),
            hard_timeout_seconds=10,
        )

        self.assertEqual(result.status, "verified", result.validation_errors)
        self.assertTrue(result.applied_in_sandbox)
        self.assertTrue(result.workspace_unchanged)
        self.assertTrue(result.sandbox_cleaned)
        self.assertIn("api_missing_fields_contract", result.required_check_ids)
        self.assertIn("demo_smoke_suite", result.required_check_ids)
        self.assertEqual(source.read_bytes(), before)
        patched = [item for item in result.check_runs if item.phase == "patched"]
        self.assertTrue(all(item.success_criterion_met for item in patched))

    def test_value_error_patch_fails_behavior_verification(self):
        result = verify_patch_in_sandbox(
            proposal(return_400=False),
            report(),
            hard_timeout_seconds=10,
        )

        self.assertEqual(result.status, "failed")
        self.assertTrue(any(
            "api_missing_fields_contract" in item
            for item in result.validation_errors
        ))

    def test_apply_helper_refuses_formal_workspace(self):
        with self.assertRaisesRegex(ValueError, "正式工作区"):
            apply_validated_patch_to_sandbox(proposal(return_400=True), ROOT)

    def test_apply_helper_can_only_use_existing_sandbox_context(self):
        candidate = proposal(return_400=True)
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            with self.assertRaisesRegex(ValueError, "上下文校验失败"):
                apply_validated_patch_to_sandbox(candidate, sandbox)

    def test_verification_rejects_changed_file_without_declared_coverage(self):
        manifest = {
            "version": 1,
            "checks": [{
                "check_id": "demo_missing_user_id",
                "runner": "demo_case",
                "target": "missing_user_id",
                "description": "没有声明文件覆盖关系的检查",
                "timeout_seconds": 5,
                "expected_exit_codes": [1],
                "purpose": "reproduction",
                "covers_files": [],
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "harness.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False),
                encoding="utf-8",
            )
            result = verify_patch_in_sandbox(
                proposal(return_400=True),
                report(),
                manifest_path=manifest_path,
                hard_timeout_seconds=10,
            )

        self.assertEqual(result.status, "rejected")
        self.assertIn("没有任何预登记检查声明覆盖", result.validation_errors[0])


if __name__ == "__main__":
    unittest.main()
