"""V2 离线测试：注册、参数校验、统一结果、文件工具和报告格式。"""

import json
import unittest

from config import resolve_capabilities
from main import format_report
from models import Evidence, IncidentReport, ToolResult
from registry import registry


def call_tool(name: str, arguments: dict) -> ToolResult:
    return ToolResult.model_validate_json(registry.execute(name, json.dumps(arguments)))


class RegistryTests(unittest.TestCase):
    def test_all_tools_are_registered(self) -> None:
        self.assertEqual(set(registry.names()), {
            "read_file", "search_code", "list_files", "retrieve_docs",
            "git_status", "git_diff", "git_log",
        })

    def test_schema_is_strict(self) -> None:
        schemas = registry.schemas()
        self.assertTrue(all(item["function"]["strict"] for item in schemas))

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


class ReportTests(unittest.TestCase):
    def test_human_readable_report(self) -> None:
        report = IncidentReport(
            summary="发现问题",
            root_cause="缺少字段",
            evidence=[Evidence(
                source_type="code", file="app.py", line=3, description="直接读取字段"
            )],
            suggested_fixes=["校验字段"],
            confidence="high",
        )
        rendered = format_report(report)
        self.assertIn("app.py:3", rendered)
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


class GitToolTests(unittest.TestCase):
    def test_git_status_is_read_only_and_successful(self) -> None:
        result = call_tool("git_status", {})
        self.assertTrue(result.ok)
        self.assertIn("output", result.data)

    def test_git_log_is_limited(self) -> None:
        result = call_tool("git_log", {"limit": 1})
        self.assertTrue(result.ok)
        self.assertIn("feat: build IncidentPilot", result.data["output"])

    def test_git_diff_blocks_sensitive_file(self) -> None:
        result = call_tool("git_diff", {"path": "api.env"})
        self.assertFalse(result.ok)
        self.assertIn("敏感", result.error or "")

    def test_git_diff_blocks_evaluation_answers(self) -> None:
        result = call_tool("git_diff", {"path": "demo_app/evals"})
        self.assertFalse(result.ok)
        self.assertIn("评测", result.error or "")

    def test_git_arguments_are_validated(self) -> None:
        result = call_tool("git_log", {"limit": 100})
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "工具参数校验失败")


if __name__ == "__main__":
    unittest.main()
