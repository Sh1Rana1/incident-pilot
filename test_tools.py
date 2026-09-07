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
        self.assertEqual(set(registry.names()), {"read_file", "search_code", "list_files"})

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

    def test_cannot_escape_project(self) -> None:
        result = call_tool("read_file", {"path": "../outside.txt"})
        self.assertFalse(result.ok)
        self.assertIn("项目根目录", result.error or "")

    def test_sensitive_file_is_blocked(self) -> None:
        result = call_tool("read_file", {"path": "api.env"})
        self.assertFalse(result.ok)
        self.assertIn("敏感", result.error or "")


class ReportTests(unittest.TestCase):
    def test_human_readable_report(self) -> None:
        report = IncidentReport(
            summary="发现问题",
            root_cause="缺少字段",
            evidence=[Evidence(file="app.py", line=3, description="直接读取字段")],
            suggested_fixes=["校验字段"],
            confidence="high",
        )
        rendered = format_report(report)
        self.assertIn("app.py:3", rendered)
        self.assertIn("置信度：high", rendered)


if __name__ == "__main__":
    unittest.main()
