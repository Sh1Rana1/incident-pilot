"""Benchmark 划分清单与不调用模型的确定性完整审计。"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from models import StrictModel


BenchmarkSplit = Literal["development", "hidden", "challenge", "runtime", "all"]

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_DIR = PROJECT_ROOT / "demo_app" / "evals"
DEFAULT_MANIFEST_PATH = DEFAULT_CASES_DIR / "_benchmark_manifest.json"
DEFAULT_AUDIT_OUTPUT = (
    DEFAULT_CASES_DIR / "results" / "v14.7-deterministic-audit.json"
)
EXPECTED_SPLIT_COUNTS = {
    "development": 5,
    "hidden": 7,
    "challenge": 2,
    "runtime": 1,
}
DERIVED_CASE_BASES = {
    "git_regression": "connection_leak",
    "misleading_documentation": "connection_leak",
    "runtime_required": "documentation_required",
}
LOG_NAME_OVERRIDES = {
    "documentation_required": "webhook_timeout_policy.log",
}
FROZEN_RESULTS = {
    "v13": DEFAULT_CASES_DIR / "results" / "v13-v14.1-development.json",
    "v14.3-development": (
        DEFAULT_CASES_DIR / "results" / "v14.3-development.json"
    ),
}


class BenchmarkManifest(StrictModel):
    schema_version: Literal[1]
    benchmark_version: str = Field(min_length=1)
    agent_baseline_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    development_cases: list[str] = Field(min_length=1)
    hidden_cases: list[str]
    challenge_cases: list[str]
    runtime_cases: list[str]
    baseline_profile: str
    runs_per_case: int = Field(ge=1, le=10)
    max_steps: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_unique_assignments(self) -> "BenchmarkManifest":
        groups = [
            self.development_cases,
            self.hidden_cases,
            self.challenge_cases,
            self.runtime_cases,
        ]
        all_ids = [case_id for group in groups for case_id in group]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("Benchmark 案例不能重复或跨集合出现")
        return self

    def case_ids(self, split: BenchmarkSplit) -> list[str]:
        mapping = {
            "development": self.development_cases,
            "hidden": self.hidden_cases,
            "challenge": self.challenge_cases,
            "runtime": self.runtime_cases,
        }
        if split == "all":
            return [
                *self.development_cases,
                *self.hidden_cases,
                *self.challenge_cases,
                *self.runtime_cases,
            ]
        return list(mapping[split])


def load_benchmark_manifest(path: Path) -> tuple[BenchmarkManifest, str]:
    raw = path.read_text(encoding="utf-8")
    manifest = BenchmarkManifest.model_validate_json(raw)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return manifest, digest


def validate_manifest_coverage(manifest: BenchmarkManifest, cases_dir: Path) -> None:
    case_files = {
        path.stem
        for path in cases_dir.glob("*.json")
        if not path.name.startswith("_")
    }
    assigned = set(manifest.case_ids("all"))
    if assigned != case_files:
        missing = sorted(case_files - assigned)
        unknown = sorted(assigned - case_files)
        raise ValueError(
            "Benchmark 清单与 Evaluation 文件不一致: "
            f"未分组={missing}, 不存在={unknown}"
        )


def evaluation_digest(cases_dir: Path, case_ids: set[str]) -> str:
    digest = hashlib.sha256()
    for case_id in sorted(case_ids):
        path = cases_dir / f"{case_id}.json"
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def select_case_ids(
    manifest: BenchmarkManifest,
    split: BenchmarkSplit,
    requested: set[str] | None,
) -> set[str]:
    available = set(manifest.case_ids(split))
    if requested is None:
        return available
    outside = requested - available
    if outside:
        raise ValueError(
            f"案例不属于 {split} 集合: {', '.join(sorted(outside))}"
        )
    return requested


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    argv: list[str],
    root: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *arguments], root, timeout=10)


def _record(
    checks: list[dict],
    name: str,
    passed: bool,
    **details,
) -> bool:
    checks.append({"name": name, "passed": passed, "details": details})
    return passed


def _case_material(root: Path, case) -> str:
    paths = [*case.evidence_files, *case.relevant_docs]
    return "\n".join(
        (root / relative).read_text(encoding="utf-8")
        for relative in paths
        if (root / relative).is_file()
    ).lower()


def _log_path(root: Path, case_id: str) -> Path:
    base_id = DERIVED_CASE_BASES.get(case_id, case_id)
    filename = LOG_NAME_OVERRIDES.get(base_id, f"{base_id}.log")
    return root / "demo_app" / "logs" / filename


def _audit_frozen_results(root: Path, checks: list[dict]) -> list[dict]:
    results: list[dict] = []
    for label, configured_path in FROZEN_RESULTS.items():
        summary_path = root / configured_path.relative_to(PROJECT_ROOT)
        exists = summary_path.is_file()
        _record(checks, f"frozen_result:{label}:exists", exists, path=str(summary_path))
        if not exists:
            continue
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        sources = payload.get("source_reports") or [payload.get("source_report")]
        sources = [item for item in sources if item]
        source_results: list[dict] = []
        for source in sources:
            source_path = (
                root / ".incident_reports" / "baselines" / label / source["file"]
            )
            digest = _sha256(source_path) if source_path.is_file() else None
            valid = digest == source.get("sha256")
            _record(
                checks,
                f"frozen_result:{label}:{source['file']}:sha256",
                valid,
                expected=source.get("sha256"),
                actual=digest,
            )
            source_results.append({
                "file": source["file"],
                "exists": source_path.is_file(),
                "sha256_matches": valid,
            })
        results.append({
            "label": label,
            "status": payload.get("status"),
            "case_count": payload.get("summary", {}).get("case_count"),
            "passed_count": payload.get("summary", {}).get("passed_count"),
            "source_reports": source_results,
        })
    return results


def run_deterministic_audit(
    project_root: Path = PROJECT_ROOT,
    *,
    execute_processes: bool = True,
) -> dict:
    """审计 Benchmark 结构、复现、隔离和冻结结果；绝不调用模型 API。"""
    from demo_app.run_case import CASES
    from evaluation import load_cases
    from harness import load_harness_manifest
    from retrieval import LocalDocumentIndex
    from tool_profiles import activate_tool_profile, reset_tool_profile
    from tools import (
        ListFilesArgs,
        ReadFileArgs,
        SearchCodeArgs,
        list_files,
        read_file,
        search_code,
    )

    root = project_root.resolve()
    cases_dir = root / "demo_app" / "evals"
    manifest_path = cases_dir / "_benchmark_manifest.json"
    checks: list[dict] = []
    warnings: list[dict] = []

    manifest, manifest_digest = load_benchmark_manifest(manifest_path)
    validate_manifest_coverage(manifest, cases_dir)
    cases = load_cases(cases_dir)
    case_map = {case.case_id: case for case in cases}
    executable_cases = list(CASES)

    _record(
        checks,
        "manifest:benchmark_version",
        manifest.benchmark_version == "v14.6",
        actual=manifest.benchmark_version,
    )
    for split, expected in EXPECTED_SPLIT_COUNTS.items():
        actual = len(manifest.case_ids(split))
        _record(
            checks,
            f"manifest:{split}:count",
            actual == expected,
            expected=expected,
            actual=actual,
        )
    _record(
        checks,
        "manifest:total_count",
        len(cases) == 15,
        expected=15,
        actual=len(cases),
    )
    _record(
        checks,
        "entrypoints:count",
        len(executable_cases) == 12 and len(set(executable_cases)) == 12,
        expected=12,
        actual=len(executable_cases),
    )

    baseline_object = _git(
        root, "cat-file", "-e", f"{manifest.agent_baseline_commit}^{{commit}}"
    )
    _record(
        checks,
        "manifest:agent_baseline_commit_exists",
        baseline_object.returncode == 0,
        commit=manifest.agent_baseline_commit,
    )

    chunks, cache_hit = LocalDocumentIndex(root).load()
    indexed_sources = {chunk.source for chunk in chunks}
    case_audits: list[dict] = []
    unsupported_keywords: list[dict] = []
    rag_misses: list[dict] = []

    for path in sorted(cases_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        parsed_id = json.loads(path.read_text(encoding="utf-8"))["case_id"]
        _record(
            checks,
            f"case:{path.stem}:filename_matches_id",
            parsed_id == path.stem,
            filename=path.stem,
            case_id=parsed_id,
        )

    for case_id in manifest.case_ids("all"):
        case = case_map[case_id]
        evidence_exists = all((root / item).is_file() for item in case.evidence_files)
        docs_exist = all((root / item).is_file() for item in case.relevant_docs)
        keywords_unique = (
            bool(case.root_cause_keywords)
            and len({item.casefold() for item in case.root_cause_keywords})
            == len(case.root_cause_keywords)
        )
        runtime_flag_valid = case.requires_runtime_evidence == (
            case_id in manifest.runtime_cases
        )
        _record(
            checks,
            f"case:{case_id}:assets",
            evidence_exists and docs_exist and keywords_unique and runtime_flag_valid,
            evidence_files=case.evidence_files,
            relevant_docs=case.relevant_docs,
            keywords_unique=keywords_unique,
            runtime_flag_valid=runtime_flag_valid,
        )

        material = _case_material(root, case)
        missing_keyword_sources: list[str] = []
        for keyword in case.root_cause_keywords:
            normalized = keyword.casefold()
            if normalized in material:
                continue
            if re.fullmatch(r"[0-9a-f]{7,40}", normalized):
                exists = _git(root, "cat-file", "-e", f"{normalized}^{{commit}}").returncode == 0
                if exists:
                    continue
            missing_keyword_sources.append(keyword)
            unsupported_keywords.append({"case_id": case_id, "keyword": keyword})
        _record(
            checks,
            f"case:{case_id}:keyword_source_support",
            not missing_keyword_sources,
            missing=missing_keyword_sources,
        )

        search_results, _, _ = LocalDocumentIndex(root).search(case.question, top_k=8)
        retrieved_sources = {item["source"] for item in search_results}
        missing_rag_docs = [
            item for item in case.relevant_docs if item not in retrieved_sources
        ]
        if missing_rag_docs:
            rag_misses.append({"case_id": case_id, "documents": missing_rag_docs})
        _record(
            checks,
            f"case:{case_id}:rag_discoverability",
            not missing_rag_docs,
            expected=case.relevant_docs,
            retrieved=sorted(retrieved_sources),
        )

        code_readable = all(
            read_file(ReadFileArgs(path=item)).ok for item in case.evidence_files
        )
        eval_blocked = not read_file(
            ReadFileArgs(path=f"demo_app/evals/{case_id}.json")
        ).ok
        token = activate_tool_profile("full")
        try:
            docs_directly_blocked = all(
                not read_file(ReadFileArgs(path=item)).ok
                for item in case.relevant_docs
            )
        finally:
            reset_tool_profile(token)
        _record(
            checks,
            f"case:{case_id}:access_boundaries",
            code_readable and eval_blocked and docs_directly_blocked,
            code_readable=code_readable,
            evaluation_blocked=eval_blocked,
            docs_directly_blocked=docs_directly_blocked,
        )

        log_path = _log_path(root, case_id)
        log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        log_valid = case.expected_exception.casefold() in log_text.casefold()
        _record(
            checks,
            f"case:{case_id}:log",
            log_valid,
            path=log_path.relative_to(root).as_posix(),
            expected_exception=case.expected_exception,
        )
        case_audits.append({
            "case_id": case_id,
            "split": next(
                split for split in EXPECTED_SPLIT_COUNTS
                if case_id in manifest.case_ids(split)
            ),
            "base_case": DERIVED_CASE_BASES.get(case_id, case_id),
            "executable": case_id in executable_cases,
            "prompt_exposed_keywords": [
                keyword for keyword in case.root_cause_keywords
                if keyword.casefold() in case.question.casefold()
            ],
            "keyword_source_support": not missing_keyword_sources,
            "rag_discoverable": not missing_rag_docs,
            "assets_valid": evidence_exists and docs_exist,
            "access_boundaries_valid": (
                code_readable and eval_blocked and docs_directly_blocked
            ),
            "log_valid": log_valid,
        })

    _record(
        checks,
        "rag:all_relevant_documents_indexed",
        all(
            document in indexed_sources
            for case in cases
            for document in case.relevant_docs
        ),
        chunk_count=len(chunks),
        cache_hit=cache_hit,
    )

    protected_paths = [
        *[f"demo_app/evals/{case_id}.json" for case_id in manifest.case_ids("all")],
        *[
            path.relative_to(root).as_posix()
            for directory in (root / "demo_app" / "checks", root / "demo_app" / "fixtures")
            for path in directory.glob("*.py")
        ],
        "benchmark.py",
        "evaluation.py",
        "llm_judge.py",
        "harness.py",
        "run_evals.py",
    ]
    blocked_reads = all(
        not read_file(ReadFileArgs(path=relative)).ok for relative in protected_paths
    )
    listed = list_files(ListFilesArgs(path="demo_app", max_depth=5))
    listed_paths = {item["path"] for item in listed.data["entries"]}
    protected_listing_hidden = not any(
        path.startswith("demo_app/evals/")
        or path.startswith("demo_app/checks/")
        or path.startswith("demo_app/fixtures/")
        for path in listed_paths
    )
    answer_search = search_code(SearchCodeArgs(query="root_cause_keywords"))
    answer_search_hidden = not any(
        item["path"].startswith("demo_app/evals/")
        or item["path"] in {"benchmark.py", "evaluation.py", "test_benchmark.py"}
        for item in answer_search.data["matches"]
    )
    _record(
        checks,
        "isolation:protected_assets",
        blocked_reads and protected_listing_hidden and answer_search_hidden,
        protected_path_count=len(protected_paths),
        blocked_reads=blocked_reads,
        protected_listing_hidden=protected_listing_hidden,
        answer_search_hidden=answer_search_hidden,
    )

    harness_manifest, harness_digest = load_harness_manifest(root / "harness.json")
    reproduction_checks = [
        item for item in harness_manifest.checks if item.purpose == "reproduction"
    ]
    reproduction_targets = [item.target for item in reproduction_checks]
    _record(
        checks,
        "harness:reproduction_mapping",
        len(reproduction_targets) == 12
        and set(reproduction_targets) == set(executable_cases),
        target_count=len(reproduction_targets),
        targets=sorted(reproduction_targets),
    )
    _record(
        checks,
        "harness:total_count",
        len(harness_manifest.checks) == 22,
        expected=22,
        actual=len(harness_manifest.checks),
    )
    for item in reproduction_checks:
        case = case_map[item.target]
        _record(
            checks,
            f"harness:{item.check_id}:coverage",
            bool(set(item.covers_files) & set(case.evidence_files)),
            covers_files=item.covers_files,
            evidence_files=case.evidence_files,
        )

    process_audits: list[dict] = []
    harness_audits: list[dict] = []
    audit_test_suite: dict | None = None
    if execute_processes:
        for case_id in executable_cases:
            case = case_map[case_id]
            for entry_name, argv in (
                ("module", [sys.executable, "-m", "demo_app.run_case", case_id]),
                ("script", [sys.executable, "demo_app/run_case.py", case_id]),
            ):
                completed = _run(argv, root, timeout=10)
                output = completed.stdout + completed.stderr
                valid = (
                    completed.returncode == 1
                    and case.expected_exception.casefold() in output.casefold()
                )
                _record(
                    checks,
                    f"reproduction:{case_id}:{entry_name}",
                    valid,
                    exit_code=completed.returncode,
                    expected_exception=case.expected_exception,
                )
                process_audits.append({
                    "case_id": case_id,
                    "entry": entry_name,
                    "exit_code": completed.returncode,
                    "expected_exception_found": (
                        case.expected_exception.casefold() in output.casefold()
                    ),
                })

        for item in harness_manifest.checks:
            if item.runner == "demo_case":
                argv = [sys.executable, "-m", "demo_app.run_case", item.target]
            elif item.runner == "unittest":
                argv = [sys.executable, "-m", "unittest", "-q", item.target]
            else:
                argv = [sys.executable, "-m", "pytest", "-q", item.target]
            completed = _run(argv, root, timeout=item.timeout_seconds)
            expectation_met = completed.returncode in item.expected_exit_codes
            expected_current_state = (
                item.purpose == "reproduction" or not item.covers_files
            )
            valid = expectation_met == expected_current_state
            _record(
                checks,
                f"harness:{item.check_id}:current_behavior",
                valid,
                exit_code=completed.returncode,
                expectation_met=expectation_met,
                expected_current_state=expected_current_state,
            )
            harness_audits.append({
                "check_id": item.check_id,
                "purpose": item.purpose,
                "exit_code": completed.returncode,
                "expectation_met": expectation_met,
                "expected_current_state": expected_current_state,
            })

        suite = _run(
            [
                sys.executable,
                "-m",
                "unittest",
                "-q",
                "test_demo_app",
                "test_benchmark",
                "test_harness",
                "test_tools",
            ],
            root,
            timeout=120,
        )
        suite_output = suite.stdout + suite.stderr
        suite_match = re.search(r"Ran\s+(\d+)\s+tests?", suite_output)
        audit_test_suite = {
            "exit_code": suite.returncode,
            "test_count": int(suite_match.group(1)) if suite_match else None,
        }
        _record(
            checks,
            "tests:audit_regression_suite",
            suite.returncode == 0,
            **audit_test_suite,
        )

    frozen_results = _audit_frozen_results(root, checks)

    evaluation_source = (root / "evaluation.py").read_text(encoding="utf-8")
    if "if not scores.expected_exception_mentioned" not in evaluation_source:
        warnings.append({
            "code": "expected_exception_not_hard_gate",
            "message": (
                "expected_exception_mentioned 当前只记录指标，不参与通过条件；"
                "报告即使未说明异常类型也可能通过。"
            ),
        })
    if "if evidence_rate < 0.5" in evaluation_source:
        warnings.append({
            "code": "partial_evidence_threshold",
            "message": (
                "当前代码 Evidence 硬门槛为 50%，列出多个必需文件的案例可能在"
                "只覆盖一半时通过。冻结历史结果沿用该规则，本次审计不改评分器。"
            ),
        })

    failed_checks = [item for item in checks if not item["passed"]]
    status = "failed" if failed_checks else (
        "passed_with_warnings" if warnings else "passed"
    )
    head = _git(root, "rev-parse", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=all")
    return {
        "schema_version": 1,
        "audit_version": "v14.7-deterministic",
        "status": status,
        "repository_commit": head.stdout.strip() if head.returncode == 0 else None,
        "working_tree_dirty": bool(dirty.stdout.strip()),
        "benchmark_version": manifest.benchmark_version,
        "benchmark_manifest_sha256": manifest_digest,
        "evaluation_cases_sha256": evaluation_digest(
            cases_dir, set(manifest.case_ids("all"))
        ),
        "harness_manifest_sha256": harness_digest,
        "summary": {
            "case_count": len(cases),
            "executable_case_count": len(executable_cases),
            "harness_check_count": len(harness_manifest.checks),
            "rag_chunk_count": len(chunks),
            "check_count": len(checks),
            "passed_check_count": len(checks) - len(failed_checks),
            "failed_check_count": len(failed_checks),
            "warning_count": len(warnings),
            "process_reproduction_count": len(process_audits),
            "harness_execution_count": len(harness_audits),
        },
        "split_counts": {
            split: len(manifest.case_ids(split)) for split in EXPECTED_SPLIT_COUNTS
        },
        "case_audits": case_audits,
        "process_reproductions": process_audits,
        "harness_executions": harness_audits,
        "audit_test_suite": audit_test_suite,
        "frozen_results": frozen_results,
        "unsupported_keywords": unsupported_keywords,
        "rag_misses": rag_misses,
        "warnings": warnings,
        "failed_checks": failed_checks,
        "checks": checks,
    }


def save_deterministic_audit(report: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="不调用模型，完整审计 IncidentPilot Benchmark"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_AUDIT_OUTPUT,
        help="JSON 审计报告路径",
    )
    parser.add_argument(
        "--skip-processes",
        action="store_true",
        help="只检查静态结构，不执行 Demo、Harness 和专项测试",
    )
    arguments = parser.parse_args()
    output = arguments.output
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    report = run_deterministic_audit(
        PROJECT_ROOT,
        execute_processes=not arguments.skip_processes,
    )
    save_deterministic_audit(report, output)
    summary = report["summary"]
    print(
        "Benchmark 确定性审计："
        f"{report['status']}；"
        f"{summary['passed_check_count']}/{summary['check_count']} 项检查通过；"
        f"警告 {summary['warning_count']} 项。"
    )
    print(f"完整 JSON：{output}")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
