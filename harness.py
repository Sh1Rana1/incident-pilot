"""V12.1.1 安全测试 Harness：模型只选择 check_id，命令由受信清单构造。"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, ValidationError, field_validator, model_validator

from models import StrictModel, ToolResult
from registry import registry
from runtime_tools import (
    begin_runtime_execution,
    complete_runtime_execution,
    current_runtime_timeout_seconds,
    runtime_environment,
    runtime_exception_message,
    runtime_exception_type,
    runtime_excerpt,
    runtime_traceback_frames,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST_PATH = ROOT / "harness.json"
MAX_CHECKS = 50
MAX_FAILED_TESTS = 20
DEMO_CASES = {
    "async_missing_await",
    "retry_non_idempotent",
    "timezone_mismatch",
    "cache_key_version",
    "pagination_off_by_one",
    "config_env_rename",
    "transaction_rollback",
    "dependency_contract_change",
    "missing_user_id",
    "schema_mismatch",
    "connection_leak",
    "documentation_required",
}
_CHECK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_UNITTEST_TARGET_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
_PROTECTED_TARGET_PARTS = {
    ".git",
    ".venv",
    ".incident_cache",
    ".incident_reports",
    ".incident_state",
    "__pycache__",
    "evals",
    "fixtures",
}
_PROTECTED_TEST_MODULES = {
    "test_demo_app",
    "test_evaluation",
    "test_experiments",
    "test_harness",
    "test_runtime_tools",
}


class HarnessCheck(StrictModel):
    check_id: str
    runner: Literal["demo_case", "unittest", "pytest"]
    target: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=300)
    timeout_seconds: int = Field(ge=1, le=120)
    expected_exit_codes: list[int] = Field(min_length=1, max_length=8)
    purpose: Literal["reproduction", "regression"] = "regression"
    covers_files: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("check_id")
    @classmethod
    def validate_check_id(cls, value: str) -> str:
        if not _CHECK_ID_PATTERN.fullmatch(value):
            raise ValueError("check_id 只能使用小写字母、数字、下划线或连字符")
        return value

    @field_validator("expected_exit_codes")
    @classmethod
    def validate_exit_codes(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("expected_exit_codes 不能重复")
        if any(item < 0 or item > 255 for item in value):
            raise ValueError("expected_exit_codes 必须在 0 到 255 之间")
        return value

    @field_validator("covers_files")
    @classmethod
    def validate_covered_files(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("covers_files 不能重复")
        for relative in value:
            if not relative or "\\" in relative or relative.startswith("/"):
                raise ValueError("covers_files 必须使用 POSIX 项目相对路径")
            parts = Path(relative).parts
            if ".." in parts or "." in parts:
                raise ValueError("covers_files 不能离开项目根目录")
        return value

    @model_validator(mode="after")
    def validate_target(self) -> "HarnessCheck":
        if self.runner == "demo_case" and self.target not in DEMO_CASES:
            raise ValueError("demo_case target 不在预登记案例中")
        if self.runner == "unittest" and not _UNITTEST_TARGET_PATTERN.fullmatch(
            self.target
        ):
            raise ValueError("unittest target 必须是模块名，不能包含命令参数")
        if self.runner == "unittest":
            parts = set(self.target.split("."))
            if parts & (_PROTECTED_TARGET_PARTS | _PROTECTED_TEST_MODULES):
                raise ValueError("unittest target 属于 Harness 内部或评测目录")
        if self.runner == "pytest":
            _resolve_pytest_target(self.target)
        return self


class HarnessManifest(StrictModel):
    version: Literal[1]
    checks: list[HarnessCheck] = Field(min_length=1, max_length=MAX_CHECKS)

    @model_validator(mode="after")
    def unique_check_ids(self) -> "HarnessManifest":
        ids = [item.check_id for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("harness.json 中的 check_id 不能重复")
        return self


class ListChecksArgs(StrictModel):
    pass


class RunCheckArgs(StrictModel):
    check_id: str = Field(
        description="harness.json 中预登记的检查 ID；不能传命令、路径或参数"
    )

    @field_validator("check_id")
    @classmethod
    def validate_check_id(cls, value: str) -> str:
        if not _CHECK_ID_PATTERN.fullmatch(value):
            raise ValueError("check_id 格式不合法")
        return value


def _resolve_pytest_target(target: str, root: Path = ROOT) -> Path:
    if any(character in target for character in ("*", "?", "[", "]")):
        raise ValueError("pytest target 不能包含通配符")
    candidate = (root / target).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("pytest target 不能离开项目根目录") from exc
    if not candidate.exists():
        raise ValueError(f"pytest target 不存在: {target}")
    relative_parts = set(candidate.relative_to(root.resolve()).parts)
    if relative_parts & _PROTECTED_TARGET_PARTS:
        raise ValueError("pytest target 属于 Harness 内部或评测目录")
    if candidate.is_file() and candidate.suffix.lower() != ".py":
        raise ValueError("pytest 文件 target 必须是 .py 文件")
    return candidate


def load_harness_manifest(
    path: Path = DEFAULT_MANIFEST_PATH,
) -> tuple[HarnessManifest, str]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise ValueError(f"找不到 Harness 清单: {path.name}") from exc
    try:
        manifest = HarnessManifest.model_validate_json(raw)
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        location = ".".join(str(item) for item in first.get("loc", ()))
        raise ValueError(
            f"Harness 清单格式错误 {location}: {first.get('msg', 'invalid')}"
        ) from exc
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return manifest, digest


def _check_digest(check: HarnessCheck) -> str:
    payload = check.model_dump_json(exclude_none=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _command_for_check(
    check: HarnessCheck,
    root: Path = ROOT,
) -> tuple[list[str], list[str]]:
    if check.runner == "demo_case":
        argv = [sys.executable, "-m", "demo_app.run_case", check.target]
        display = ["<current-python>", "-m", "demo_app.run_case", check.target]
    elif check.runner == "unittest":
        argv = [sys.executable, "-m", "unittest", "-q", check.target]
        display = ["<current-python>", "-m", "unittest", "-q", check.target]
    else:
        relative = _resolve_pytest_target(check.target, root).relative_to(root).as_posix()
        argv = [sys.executable, "-m", "pytest", "-q", relative]
        display = ["<current-python>", "-m", "pytest", "-q", relative]
    return argv, display


def _test_counts(output: str, runner: str, returncode: int) -> tuple[int, int]:
    if runner == "unittest":
        ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
        total = int(ran.group(1)) if ran else 0
        failures = sum(
            int(value)
            for value in re.findall(r"(?:failures|errors)=(\d+)", output)
        )
        return max(total - failures, 0), failures
    if runner == "pytest":
        passed = sum(int(item) for item in re.findall(r"(\d+) passed", output))
        failed = sum(int(item) for item in re.findall(r"(\d+) failed", output))
        return passed, failed
    return 0, 0


def _failed_tests(output: str) -> list[str]:
    names: list[str] = []
    for pattern in (
        r"^(?:FAIL|ERROR):\s+([^\s(]+)",
        r"^FAILED\s+([^\s]+::[^\s]+)",
    ):
        names.extend(re.findall(pattern, output, re.MULTILINE))
    return list(dict.fromkeys(names))[:MAX_FAILED_TESTS]


@registry.register(
    name="list_checks",
    description=(
        "列出 harness.json 中由项目所有者预登记的安全测试。返回 ID、说明、"
        "Runner、超时和预期退出码，不暴露可由模型修改的命令。"
    ),
    arguments_model=ListChecksArgs,
)
def list_checks_tool(_arguments: ListChecksArgs) -> ToolResult:
    try:
        manifest, manifest_digest = load_harness_manifest()
    except ValueError as exc:
        return ToolResult.failure(str(exc), reason="harness_manifest_invalid")
    return ToolResult.success({
        "manifest_version": manifest.version,
        "manifest_sha256": manifest_digest,
        "checks": [
            {
                "check_id": check.check_id,
                "runner": check.runner,
                "description": check.description,
                "timeout_seconds": check.timeout_seconds,
                "expected_exit_codes": check.expected_exit_codes,
                "purpose": check.purpose,
                "covers_files": check.covers_files,
            }
            for check in manifest.checks
        ],
    })


@registry.register(
    name="run_check",
    description=(
        "运行一个由项目所有者在 harness.json 中预登记的测试，返回结构化测试结果"
        "和系统 Runtime ID。只能提交 check_id，不能提交命令、参数、路径或环境变量。"
    ),
    arguments_model=RunCheckArgs,
)
def run_check_tool(arguments: RunCheckArgs) -> ToolResult:
    try:
        manifest, manifest_digest = load_harness_manifest()
    except ValueError as exc:
        return ToolResult.failure(str(exc), reason="harness_manifest_invalid")
    check = next(
        (item for item in manifest.checks if item.check_id == arguments.check_id),
        None,
    )
    if check is None:
        return ToolResult.failure(
            f"Harness 检查未登记: {arguments.check_id}",
            reason="harness_check_not_registered",
        )

    execution_id, database_path, prior_result = begin_runtime_execution(
        f"check:{check.check_id}:{_check_digest(check)}"
    )
    if prior_result is not None:
        return prior_result

    def finalize(result: ToolResult) -> ToolResult:
        return complete_runtime_execution(result, execution_id, database_path)

    try:
        argv, display_argv = _command_for_check(check)
    except ValueError as exc:
        return finalize(ToolResult.failure(
            str(exc), reason="harness_target_invalid", check_id=check.check_id
        ))
    timeout_seconds = min(
        check.timeout_seconds,
        current_runtime_timeout_seconds(),
    )
    run_id = f"runtime-check-{check.check_id}-{uuid4().hex[:12]}"
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_environment(),
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return finalize(ToolResult.failure(
            f"预登记检查运行超过 {timeout_seconds} 秒，已终止",
            run_id=run_id,
            check_id=check.check_id,
            timed_out=True,
            timeout_seconds=timeout_seconds,
            stdout_excerpt=runtime_excerpt(exc.stdout),
            stderr_excerpt=runtime_excerpt(exc.stderr),
        ))
    except OSError as exc:
        return finalize(ToolResult.failure(
            f"无法启动预登记检查: {exc}",
            run_id=run_id,
            check_id=check.check_id,
            reason="harness_start_failed",
        ))

    raw_stdout = completed.stdout or ""
    raw_stderr = completed.stderr or ""
    combined = raw_stdout + "\n" + raw_stderr
    passed_count, failed_count = _test_counts(
        combined, check.runner, completed.returncode
    )
    return finalize(ToolResult.success({
        "run_id": run_id,
        "execution_id": execution_id,
        "check_id": check.check_id,
        "runner": check.runner,
        "description": check.description,
        "manifest_sha256": manifest_digest,
        "check_definition_sha256": _check_digest(check),
        "exit_code": completed.returncode,
        "expected_exit_codes": check.expected_exit_codes,
        "purpose": check.purpose,
        "covers_files": check.covers_files,
        "expectation_met": completed.returncode in check.expected_exit_codes,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "failed_tests": _failed_tests(combined),
        "exception_type": runtime_exception_type(raw_stderr),
        "exception_message": runtime_exception_message(raw_stderr),
        "traceback_frames": runtime_traceback_frames(raw_stderr),
        "timed_out": False,
        "timeout_seconds": timeout_seconds,
        "argv": display_argv,
        "stdout_excerpt": runtime_excerpt(raw_stdout),
        "stderr_excerpt": runtime_excerpt(raw_stderr),
    }))
