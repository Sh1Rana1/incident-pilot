"""V7 Observation 提取与证据来源验证测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from models import DiagnosticClaim, Evidence, IncidentReport
from provenance import build_observation, validate_report_provenance
from retrieval import split_markdown


def report_for(evidence: Evidence) -> IncidentReport:
    return IncidentReport(
        summary="测试证据链",
        root_cause="由一条真实证据支持",
        claims=[DiagnosticClaim(
            claim_id="C1", statement="测试结论", evidence_ids=[evidence.evidence_id]
        )],
        evidence=[evidence],
        suggested_fixes=[],
        confidence="medium",
    )


class ProvenanceTests(unittest.TestCase):
    def test_search_code_excerpt_keeps_late_matches(self) -> None:
        matches = [
            {"path": f"demo_app/app/noise_{index}.py", "line": index,
             "content": "user_id = value" + "x" * 80}
            for index in range(1, 12)
        ]
        matches.append({
            "path": "demo_app/app/service.py",
            "line": 9,
            "content": 'user_id = payload["user_id"]',
        })
        payload = json.dumps({
            "ok": True,
            "data": {"query": "user_id", "matches": matches},
            "error": None,
            "meta": {},
        })

        observation, _ = build_observation(
            "obs-001", "call-search", 1, "search_code",
            json.dumps({"query": "user_id"}), payload, 1,
        )

        self.assertGreater(len(observation.result_excerpt), 1000)
        self.assertIn("demo_app/app/service.py", observation.result_excerpt)
        self.assertIn('payload[\\\"user_id\\\"]', observation.result_excerpt)

    def test_long_rag_chunks_keep_real_line_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "long.md"
            document.write_text(
                "# Long\n" + "\n".join(f"line-{index}-" + "x" * 30 for index in range(80)),
                encoding="utf-8",
            )
            chunks = split_markdown(document, root)

        self.assertGreater(len(chunks), 1)
        self.assertGreater(chunks[1].line_start, chunks[0].line_start)
        self.assertGreaterEqual(chunks[1].line_end, chunks[1].line_start)

    def test_read_file_line_must_be_inside_observed_range(self) -> None:
        payload = json.dumps({
            "ok": True,
            "data": {"path": "main.py", "lines": [
                {"line": 1, "content": "first"},
                {"line": 2, "content": "second"},
            ]},
            "error": None,
            "meta": {},
        })
        observation, _ = build_observation(
            "obs-001", "call-1", 1, "read_file", '{"path":"main.py"}', payload, 1,
        )
        evidence = Evidence(
            evidence_id="E1", observation_id="obs-001", source_type="code",
            file="main.py", line_start=3, line_end=3, commit_hash=None,
            runtime_id=None,
            description="未读取的行",
        )

        errors = validate_report_provenance(report_for(evidence), [observation])
        self.assertTrue(any("不在 obs-001" in item for item in errors))

    def test_git_commit_can_be_grounded_without_fake_file(self) -> None:
        commit = "61932b9b542aadc3fa14a8243dda04cf9b74546d"
        payload = json.dumps({
            "ok": True,
            "data": {"output": f"{commit}\tAuthor\t2026-09-11\tfeat: demo"},
            "error": None,
            "meta": {},
        })
        observation, _ = build_observation(
            "obs-007", "call-7", 2, "git_log", '{"limit":5}', payload, 2,
        )
        evidence = Evidence(
            evidence_id="E7", observation_id="obs-007", source_type="git",
            file="", line_start=None, line_end=None, commit_hash="61932b9",
            runtime_id=None,
            description="Git 历史包含该提交",
        )

        self.assertEqual(validate_report_provenance(report_for(evidence), [observation]), [])

    def test_claim_cannot_reference_missing_evidence(self) -> None:
        report = IncidentReport(
            summary="测试", root_cause="测试",
            claims=[DiagnosticClaim(
                claim_id="C1", statement="没有证据", evidence_ids=["E404"]
            )],
            evidence=[], suggested_fixes=[], confidence="medium",
        )
        errors = validate_report_provenance(report, [])
        self.assertTrue(any("不存在的证据" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
