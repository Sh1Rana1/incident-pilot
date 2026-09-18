"""V10 离线测试：注册、隔离、只读工具和报告展示。"""

import json
import unittest
from pathlib import Path

from config import resolve_capabilities
from main import format_report
from models import DiagnosticClaim, Evidence, IncidentReport, ToolResult
from registry import registry
import runtime_tools  # noqa: F401：触发 V9 Runtime 工具注册


def call_tool(name: str, arguments: dict) -> ToolResult:
    return ToolResult.model_validate_json(registry.execute(name, json.dumps(arguments)))


class RegistryTests(unittest.TestCase):
    def test_all_tools_are_registered(self) -> None:
        self.assertEqual(set(registry.names()), {
            "read_file", "search_code", "list_files", "retrieve_docs",
            "git_status", "git_diff", "git_log",
            "run_demo_case", "list_checks", "run_check",
        })

    def test_schema_is_strict(self) -> None:
        schemas = registry.schemas()
        self.assertTrue(all(item["function"]["strict"] for item in schemas))

    def test_strict_schema_requires_nullable_read_file_fields(self) -> None:
        strict_schema = next(
            item["function"]["parameters"]
            for item in registry.schemas(strict=True)
            if item["function"]["name"] == "read_file"
        )
        properties = strict_schema["properties"]

        self.assertEqual(set(strict_schema["required"]), set(properties))
        self.assertNotIn("default", properties["start_line"])
        self.assertIn({"type": "null"}, properties["start_line"]["anyOf"])
        self.assertIn({"type": "null"}, properties["end_line"]["anyOf"])

    def test_non_strict_schema_keeps_optional_read_file_fields(self) -> None:
        schema = next(
            item["function"]["parameters"]
            for item in registry.schemas(strict=False)
            if item["function"]["name"] == "read_file"
        )

        self.assertEqual(schema["required"], ["path"])
        self.assertIsNone(schema["properties"]["start_line"]["default"])

    def test_unknown_tool_has_standard_result(self) -> None:
        result = call_tool("missing", {})
        self.assertFalse(result.ok)
        self.assertIn("不存在", result.error or "")

    def test_invalid_arguments_have_standard_result(self) -> None:
        result = call_tool("search_code", {"wrong": "run_agent"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "工具参数校验失败")


class ConfigTests(unittest.TestCase):
    def test_openai_auto_mode(self) -> None:
        self.assertEqual(
            resolve_capabilities("https://api.openai.com/v1"),
            ("json_schema", True),
        )

    def test_deepseek_auto_mode(self) -> None:
        self.assertEqual(
            resolve_capabilities("https://api.deepseek.com/beta"),
            ("json_object", True),
        )

    def test_generic_provider_uses_conservative_defaults(self) -> None:
        self.assertEqual(
            resolve_capabilities("https://example.com/v1"),
            ("json_object", False),
        )

    def test_env_can_override_capabilities(self) -> None:
        self.assertEqual(
            resolve_capabilities("https://example.com/v1", "text", "true"),
            ("text", True),
        )


class FileToolTests(unittest.TestCase):
    def test_read_file_returns_lines(self) -> None:
        result = call_tool("read_file", {"path": "main.py"})
        self.assertTrue(result.ok)
        self.assertTrue(any("def main" in line["content"] for line in result.data["lines"]))

    def test_read_file_returns_inclusive_targeted_lines(self) -> None:
        result = call_tool("read_file", {
            "path": "demo_app/run_case.py",
            "start_line": 35,
            "end_line": 45,
        })

        self.assertTrue(result.ok)
        self.assertEqual(result.data["lines"][0]["line"], 35)
        self.assertEqual(result.data["lines"][-1]["line"], 45)
        self.assertEqual(result.meta["line_start"], 35)
        self.assertEqual(result.meta["line_end"], 45)
        self.assertTrue(result.meta["targeted"])

    def test_read_file_rejects_reverse_or_oversized_range(self) -> None:
        reverse = call_tool("read_file", {
            "path": "main.py", "start_line": 20, "end_line": 10,
        })
        oversized = call_tool("read_file", {
            "path": "main.py", "start_line": 1, "end_line": 31,
        })

        self.assertFalse(reverse.ok)
        self.assertIn("不能小于", reverse.error or "")
        self.assertFalse(oversized.ok)
        self.assertIn("最多 30 行", oversized.error or "")

    def test_read_file_start_only_defaults_to_thirty_line_window(self) -> None:
        result = call_tool("read_file", {
            "path": "README.md", "start_line": 100,
        })

        self.assertTrue(result.ok)
        self.assertEqual(result.data["lines"][0]["line"], 100)
        self.assertLessEqual(len(result.data["lines"]), 30)

    def test_search_code_returns_structured_matches(self) -> None:
        result = call_tool("search_code", {"query": "run_agent"})
        self.assertTrue(result.ok)
        self.assertTrue(any(match["path"] == "main.py" for match in result.data["matches"]))

    def test_list_files_returns_project_structure(self) -> None:
        result = call_tool("list_files", {"path": ".", "max_depth": 2})
        self.assertTrue(result.ok)
        paths = {entry["path"] for entry in result.data["entries"]}
        self.assertIn("agent.py", paths)
        self.assertNotIn("api.env", paths)
        self.assertNotIn(".incident_cache", paths)

    def test_cannot_escape_project(self) -> None:
        result = call_tool("read_file", {"path": "../outside.txt"})
        self.assertFalse(result.ok)
        self.assertIn("项目根目录", result.error or "")

    def test_sensitive_file_is_blocked(self) -> None:
        result = call_tool("read_file", {"path": "api.env"})
        self.assertFalse(result.ok)
        self.assertIn("敏感", result.error or "")

    def test_evaluation_answers_are_not_visible(self) -> None:
        path = "demo_app/evals/missing_user_id.json"
        read_result = call_tool("read_file", {"path": path})
        self.assertFalse(read_result.ok)
        harness_result = call_tool("read_file", {"path": "harness.json"})
        self.assertFalse(harness_result.ok)
        search_result = call_tool("search_code", {"query": "root_cause_keywords"})
        self.assertFalse(any(
            "demo_app/evals/" in match["path"]
            for match in search_result.data["matches"]
        ))
        list_result = call_tool("list_files", {"path": "demo_app", "max_depth": 3})
        self.assertFalse(any(
            "/evals/" in f"/{entry['path']}/"
            for entry in list_result.data["entries"]
        ))

    def test_evaluation_infrastructure_is_hidden_during_agent_run(self) -> None:
        allowed = {"list_files", "search_code", "read_file"}
        listed = ToolResult.model_validate_json(registry.execute(
            "list_files", '{"path":".","max_depth":1}',
            allowed_tools=allowed, tool_profile="code_only",
        ))
        paths = {item["path"] for item in listed.data["entries"]}
        self.assertNotIn("test_evaluation.py", paths)
        self.assertNotIn("run_evals.py", paths)
        read_result = ToolResult.model_validate_json(registry.execute(
            "read_file", '{"path":"test_evaluation.py"}',
            allowed_tools=allowed, tool_profile="code_only",
        ))
        self.assertFalse(read_result.ok)
        searched = ToolResult.model_validate_json(registry.execute(
            "search_code", '{"query":"missing_root_cause_keywords"}',
            allowed_tools=allowed, tool_profile="code_only",
        ))
        self.assertFalse(any(
            item["path"] in {"evaluation.py", "test_evaluation.py"}
            for item in searched.data["matches"]
        ))

    def test_all_tests_and_runtime_internals_are_hidden(self) -> None:
        blocked = {
            "test_graph.py", "test_doctor.py", "harness.py",
            "runtime_tools.py", "doctor.py", "benchmark.py",
        }
        listed = call_tool("list_files", {"path": ".", "max_depth": 1})
        listed_paths = {item["path"] for item in listed.data["entries"]}
        self.assertFalse(blocked & listed_paths)
        for path in blocked:
            with self.subTest(path=path):
                self.assertFalse(call_tool("read_file", {"path": path}).ok)
        searched = call_tool(
            "search_code", {"query": "API 入口缺少 user_id 校验"}
        )
        self.assertTrue(searched.ok)
        self.assertFalse(any(
            item["path"].startswith("test_") or item["path"] in blocked
            for item in searched.data["matches"]
        ))
        broad_search = call_tool("search_code", {"query": "user_id"})
        self.assertTrue(broad_search.ok)
        self.assertFalse(any(
            Path(item["path"]).name.startswith("test_")
            or Path(item["path"]).name in blocked
            for item in broad_search.data["matches"]
        ))

    def test_demo_answer_tests_are_hidden_during_agent_run(self) -> None:
        allowed = {"list_files", "search_code", "read_file"}
        result = ToolResult.model_validate_json(registry.execute(
            "read_file", '{"path":"test_demo_app.py"}',
            allowed_tools=allowed, tool_profile="full_runtime",
        ))
        self.assertFalse(result.ok)
        searched = ToolResult.model_validate_json(registry.execute(
            "search_code", '{"query":"timeout_policy_violation"}',
            allowed_tools=allowed, tool_profile="full_runtime",
        ))
        self.assertFalse(any(
            item["path"] in {"test_demo_app.py", "test_runtime_tools.py"}
            for item in searched.data["matches"]
        ))

    def test_generated_evaluation_reports_are_not_visible(self) -> None:
        listed = call_tool("list_files", {"path": ".", "max_depth": 2})
        self.assertNotIn(".incident_reports", str(listed.data))
        result = call_tool(
            "read_file",
            {"path": ".incident_reports/eval-20260911-182414.json"},
        )
        self.assertFalse(result.ok)
        self.assertIn("内部", result.error or "")

    def test_persistent_state_database_is_not_visible_to_agent(self) -> None:
        listed = call_tool("list_files", {"path": ".", "max_depth": 2})
        self.assertNotIn(".incident_state", str(listed.data))
        result = call_tool(
            "read_file",
            {"path": ".incident_state/incident_pilot.sqlite3"},
        )
        self.assertFalse(result.ok)
        self.assertIn("内部", result.error or "")

    def test_profile_hides_rag_documents_from_file_tools(self) -> None:
        allowed = {"read_file", "search_code", "list_files"}
        read_result = ToolResult.model_validate_json(registry.execute(
            "read_file",
            '{"path":"demo_app/docs/api.md"}',
            allowed_tools=allowed,
            tool_profile="code_only",
        ))
        self.assertFalse(read_result.ok)
        self.assertEqual(read_result.meta["reason"], "rag_required_for_path")

        search_result = ToolResult.model_validate_json(registry.execute(
            "search_code",
            '{"query":"MIG-2026-001"}',
            allowed_tools=allowed,
            tool_profile="code_only",
        ))
        self.assertFalse(any(
            match["path"].startswith("demo_app/docs/")
            for match in search_result.data["matches"]
        ))
        self.assertFalse(any(
            match["path"].endswith(".md")
            for match in search_result.data["matches"]
        ))

        list_result = ToolResult.model_validate_json(registry.execute(
            "list_files",
            '{"path":"demo_app","max_depth":3}',
            allowed_tools=allowed,
            tool_profile="code_rag",
        ))
        self.assertFalse(any(
            entry["path"].startswith("demo_app/docs/")
            for entry in list_result.data["entries"]
        ))
        self.assertFalse(any(
            entry["path"].endswith(".md")
            for entry in list_result.data["entries"]
        ))

    def test_profile_cannot_read_hidden_provider_fixture(self) -> None:
        result = ToolResult.model_validate_json(registry.execute(
            "read_file",
            '{"path":"demo_app/fixtures/provider_gateway.py"}',
            allowed_tools={"read_file"},
            tool_profile="full",
        ))
        self.assertFalse(result.ok)
        self.assertIn("内部", result.error or "")
        listed = ToolResult.model_validate_json(registry.execute(
            "list_files",
            '{"path":"demo_app","max_depth":3}',
            allowed_tools={"list_files"},
            tool_profile="full",
        ))
        self.assertNotIn("fixtures", str(listed.data))
        searched = ToolResult.model_validate_json(registry.execute(
            "search_code",
            '{"query":"PROVIDER_TIMEOUT_LIMIT_SECONDS"}',
            allowed_tools={"search_code"},
            tool_profile="full",
        ))
        self.assertFalse(any(
            match["path"].startswith("demo_app/fixtures/")
            for match in searched.data["matches"]
        ))


class ReportTests(unittest.TestCase):
    def test_human_readable_report(self) -> None:
        report = IncidentReport(
            summary="发现问题",
            root_cause="缺少字段",
            claims=[DiagnosticClaim(
                claim_id="C1", statement="缺少字段", evidence_ids=["E1"]
            )],
            evidence=[Evidence(
                evidence_id="E1", observation_id="obs-001", source_type="code",
                file="app.py", line_start=3, line_end=3, commit_hash=None,
                runtime_id=None,
                description="直接读取字段"
            )],
            suggested_fixes=["校验字段"],
            confidence="high",
        )
        rendered = format_report(report)
        self.assertIn("app.py:3", rendered)
        self.assertIn("obs-001", rendered)
        self.assertIn("置信度：high", rendered)


class RetrievalToolTests(unittest.TestCase):
    def test_retrieve_docs_returns_citations(self) -> None:
        result = call_tool("retrieve_docs", {"query": "response_format json_schema", "top_k": 3})
        self.assertTrue(result.ok)
        self.assertGreater(len(result.data["chunks"]), 0)
        first = result.data["chunks"][0]
        self.assertIn("source", first)
        self.assertIn("section", first)
        self.assertIn("line_start", first)
        self.assertIn("line_end", first)
        self.assertIn("score", first)

    def test_retrieve_docs_uses_cache_on_second_call(self) -> None:
        call_tool("retrieve_docs", {"query": "checkpoint", "top_k": 2})
        second = call_tool("retrieve_docs", {"query": "checkpoint", "top_k": 2})
        self.assertTrue(second.ok)
        self.assertTrue(second.meta["cache_hit"])

    def test_demo_api_query_retrieves_demo_document(self) -> None:
        result = call_tool(
            "retrieve_docs",
            {"query": "POST users缺少user_id应该返回400", "top_k": 3},
        )
        sources = {chunk["source"] for chunk in result.data["chunks"]}
        self.assertTrue(any(source.startswith("demo_app/docs/") for source in sources))

    def test_schema_migration_query_retrieves_database_document(self) -> None:
        result = call_tool(
            "retrieve_docs",
            {"query": "user_id重命名external_id数据库迁移", "top_k": 3},
        )
        sources = {chunk["source"] for chunk in result.data["chunks"]}
        self.assertIn("demo_app/docs/database.md", sources)

    def test_runtime_timeout_query_prioritizes_supplier_contract(self) -> None:
        result = call_tool(
            "retrieve_docs",
            {
                "query": "timeout_policy_violation timeout_seconds 配置约定",
                "top_k": 3,
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            result.data["chunks"][0]["source"],
            "demo_app/docs/integrations.md",
        )


class GitToolTests(unittest.TestCase):
    def test_git_status_is_read_only_and_successful(self) -> None:
        result = call_tool("git_status", {})
        self.assertTrue(result.ok)
        self.assertIn("output", result.data)

    def test_git_log_is_limited(self) -> None:
        result = call_tool("git_log", {"limit": 1})
        self.assertTrue(result.ok)
        lines = [line for line in result.data["output"].splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(lines[0].split("\t")), 4)

    def test_git_diff_blocks_sensitive_file(self) -> None:
        result = call_tool("git_diff", {"path": "api.env"})
        self.assertFalse(result.ok)
        self.assertIn("敏感", result.error or "")

    def test_git_diff_blocks_evaluation_answers(self) -> None:
        result = call_tool("git_diff", {"path": "demo_app/evals"})
        self.assertFalse(result.ok)
        self.assertIn("评测", result.error or "")

    def test_git_diff_rejects_broad_repository_path(self) -> None:
        result = call_tool("git_diff", {"path": "."})
        self.assertFalse(result.ok)
        self.assertIn("文件", result.error or "")

    def test_git_arguments_are_validated(self) -> None:
        result = call_tool("git_log", {"limit": 100})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "工具参数校验失败")


if __name__ == "__main__":
    unittest.main()
