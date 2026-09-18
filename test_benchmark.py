"""V14 Benchmark 划分、答案隔离和基线保存测试；不调用模型。"""

import json
import tempfile
import unittest
from pathlib import Path

from benchmark import (
    default_audit_output,
    evaluation_digest,
    load_benchmark_manifest,
    run_deterministic_audit,
    save_deterministic_audit,
    select_case_ids,
    validate_manifest_coverage,
)
from evaluation import load_cases
from retrieval import LocalDocumentIndex
from run_evals import _baseline_output_path


ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT / "demo_app" / "evals"
MANIFEST_PATH = CASES_DIR / "_benchmark_manifest.json"
BASELINE_SUMMARY_PATH = CASES_DIR / "results" / "v13-v14.1-development.json"


class BenchmarkManifestTests(unittest.TestCase):
    def test_manifest_covers_every_case_once(self):
        manifest, digest = load_benchmark_manifest(MANIFEST_PATH)
        validate_manifest_coverage(manifest, CASES_DIR)
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(manifest.case_ids("all")), 15)

    def test_development_set_is_frozen(self):
        manifest, _ = load_benchmark_manifest(MANIFEST_PATH)
        self.assertEqual(manifest.development_cases, [
            "missing_user_id",
            "schema_mismatch",
            "connection_leak",
            "async_missing_await",
            "retry_non_idempotent",
        ])
        self.assertEqual(manifest.hidden_cases, [
            "documentation_required",
            "timezone_mismatch",
            "cache_key_version",
            "pagination_off_by_one",
            "config_env_rename",
            "transaction_rollback",
            "dependency_contract_change",
        ])
        self.assertEqual(manifest.challenge_cases, [
            "git_regression", "misleading_documentation",
        ])
        self.assertEqual(manifest.runtime_cases, ["runtime_required"])

    def test_case_selection_rejects_cross_split_tuning(self):
        manifest, _ = load_benchmark_manifest(MANIFEST_PATH)
        self.assertEqual(
            select_case_ids(manifest, "development", {"missing_user_id"}),
            {"missing_user_id"},
        )
        with self.assertRaisesRegex(ValueError, "不属于 development"):
            select_case_ids(manifest, "development", {"documentation_required"})

    def test_case_loader_ignores_internal_manifest(self):
        cases = load_cases(CASES_DIR)
        self.assertEqual(len(cases), 15)
        self.assertNotIn("_benchmark_manifest", {case.case_id for case in cases})
        digest = evaluation_digest(CASES_DIR, {case.case_id for case in cases})
        self.assertEqual(len(digest), 64)

    def test_evaluation_references_existing_non_incident_documents(self):
        for case in load_cases(CASES_DIR):
            for relative in case.relevant_docs:
                self.assertTrue((ROOT / relative).is_file(), relative)
                self.assertNotIn("/incidents/", relative.replace("\\", "/"))

    def test_rag_index_contains_no_answer_incident_documents(self):
        chunks, _ = LocalDocumentIndex(ROOT).load()
        sources = {chunk.source for chunk in chunks}
        self.assertFalse(any("/incidents/" in f"/{source}" for source in sources))
        self.assertIn("demo_app/docs/api.md", sources)

    def test_business_code_has_no_embedded_answer_markers(self):
        forbidden = ("BUG-", "故意没有释放", "故意保留了迁移前")
        for path in (ROOT / "demo_app" / "app").glob("*.py"):
            content = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertFalse(any(marker in content for marker in forbidden))

    def test_baseline_path_is_scoped_and_rejects_traversal(self):
        path = _baseline_output_path("v13", "v14.1", "development", "stamp")
        self.assertEqual(path.parent.name, "v13")
        with self.assertRaisesRegex(ValueError, "baseline label"):
            _baseline_output_path("../outside", "v14.1", "development", "stamp")

    def test_committed_baseline_summary_matches_frozen_development_set(self):
        manifest, _ = load_benchmark_manifest(MANIFEST_PATH)
        baseline = json.loads(BASELINE_SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            {item["case_id"] for item in baseline["cases"]},
            set(manifest.development_cases),
        )
        self.assertEqual(baseline["summary"]["case_count"], 5)
        self.assertEqual(baseline["summary"]["passed_count"], 1)
        self.assertEqual(baseline["summary"]["pass_rate"], 0.2)
        self.assertTrue(baseline["source_audit"]["passed"])
        self.assertEqual(baseline["source_audit"]["forbidden_paths_found"], [])
        self.assertTrue(all(
            len(item["sha256"]) == 64 for item in baseline["source_reports"]
        ))

    def test_benchmark_implementation_is_hidden_from_agent_file_tools(self):
        from tools import read_file, search_code, ReadFileArgs, SearchCodeArgs
        self.assertFalse(read_file(ReadFileArgs(path="benchmark.py")).ok)
        result = search_code(SearchCodeArgs(query="agent_baseline_commit"))
        self.assertTrue(result.ok)
        self.assertFalse(any(
            item["path"] in {"benchmark.py", "test_benchmark.py"}
            for item in result.data["matches"]
        ))

    def test_complete_static_deterministic_audit_passes(self):
        report = run_deterministic_audit(ROOT, execute_processes=False)
        self.assertEqual(report["status"], "passed_with_warnings")
        self.assertEqual(report["summary"]["case_count"], 15)
        self.assertEqual(report["summary"]["executable_case_count"], 12)
        self.assertEqual(report["summary"]["harness_check_count"], 22)
        self.assertEqual(report["summary"]["failed_check_count"], 0)
        self.assertEqual(report["unsupported_keywords"], [])
        self.assertEqual(report["rag_misses"], [])
        self.assertEqual(
            {item["code"] for item in report["warnings"]},
            {
                "expected_exception_not_hard_gate",
                "partial_evidence_threshold",
            },
        )

    def test_deterministic_audit_report_can_be_saved(self):
        report = run_deterministic_audit(ROOT, execute_processes=False)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "audit.json"
            save_deterministic_audit(report, output)
            saved = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["audit_version"], "v14.8-deterministic")
        self.assertEqual(saved["status"], "passed_with_warnings")

    def test_default_audit_output_is_ignored_and_existing_report_is_immutable(self):
        output = default_audit_output(ROOT, "20260919-020000")
        self.assertEqual(
            output,
            ROOT / ".incident_reports" / "audits" /
            "deterministic-audit-20260919-020000.json",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            existing = Path(temporary_directory) / "audit.json"
            existing.write_text("original", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "拒绝覆盖"):
                save_deterministic_audit({"status": "passed"}, existing)
            self.assertEqual(existing.read_text(encoding="utf-8"), "original")


if __name__ == "__main__":
    unittest.main()
