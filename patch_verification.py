"""V13 在临时隔离副本应用候选补丁并运行预登记 Harness。"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter

from harness import (
    DEFAULT_MANIFEST_PATH,
    HarnessCheck,
    _command_for_check,
    _failed_tests,
    _test_counts,
    load_harness_manifest,
)
from models import (
    IncidentReport,
    PatchCheckRun,
    PatchProposal,
    PatchProposalDraft,
    PatchVerificationResult,
)
from patching import apply_validated_patch_to_sandbox, validate_patch_draft
from runtime_tools import runtime_environment


ROOT = Path(__file__).resolve().parent
COPY_EXCLUDED_PARTS = {
    ".git", ".venv", ".incident_cache", ".incident_reports",
    ".incident_state", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", "build", "dist", "node_modules",
}
MAX_CAPTURE_CHARS = 4_000


def _copy_project(source_root: Path, sandbox_root: Path) -> None:
    """复制运行检查所需项目内容；跳过密钥、状态、Git 和所有符号链接。"""
    source_root = source_root.resolve()
    for current, directory_names, file_names in os.walk(
        source_root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current)
        directory_names[:] = [
            name for name in directory_names
            if name.lower() not in COPY_EXCLUDED_PARTS
            and not (current_path / name).is_symlink()
        ]
        relative_directory = current_path.relative_to(source_root)
        destination_directory = sandbox_root / relative_directory
        destination_directory.mkdir(parents=True, exist_ok=True)
        for name in file_names:
            source = current_path / name
            lower_name = name.lower()
            is_secret_env = (
                lower_name == ".env"
                or lower_name.startswith(".env.")
                or lower_name == "api.env"
                or lower_name.startswith("api.env.")
            )
            if is_secret_env or source.is_symlink():
                continue
            shutil.copy2(source, destination_directory / name)


def _excerpt(value: str, sandbox_root: Path) -> str:
    return value.replace(str(sandbox_root), "<patch-sandbox>")[-MAX_CAPTURE_CHARS:]


def _run_check(
    check: HarnessCheck,
    sandbox_root: Path,
    phase: str,
    hard_timeout_seconds: int,
) -> PatchCheckRun:
    started = perf_counter()
    timeout = min(check.timeout_seconds, hard_timeout_seconds)
    try:
        argv, _display = _command_for_check(check, sandbox_root)
        completed = subprocess.run(
            argv,
            cwd=sandbox_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=runtime_environment(),
            timeout=timeout,
            check=False,
            shell=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        passed, failed = _test_counts(
            stdout + "\n" + stderr,
            check.runner,
            completed.returncode,
        )
        expectation_met = completed.returncode in check.expected_exit_codes
        criterion = (
            completed.returncode == 0 and not expectation_met
            if phase == "patched" and check.purpose == "reproduction"
            else expectation_met
        )
        return PatchCheckRun(
            check_id=check.check_id,
            phase=phase,
            purpose=check.purpose,
            exit_code=completed.returncode,
            expected_exit_codes=check.expected_exit_codes,
            expectation_met=expectation_met,
            success_criterion_met=criterion,
            passed_count=passed,
            failed_count=failed,
            failed_tests=_failed_tests(stdout + "\n" + stderr),
            stdout_excerpt=_excerpt(stdout, sandbox_root),
            stderr_excerpt=_excerpt(stderr, sandbox_root),
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
    except subprocess.TimeoutExpired as exc:
        return PatchCheckRun(
            check_id=check.check_id,
            phase=phase,
            purpose=check.purpose,
            expected_exit_codes=check.expected_exit_codes,
            timed_out=True,
            stdout_excerpt=_excerpt(str(exc.stdout or ""), sandbox_root),
            stderr_excerpt=_excerpt(str(exc.stderr or ""), sandbox_root),
            error=f"检查超过 {timeout} 秒，已终止",
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
    except (OSError, ValueError) as exc:
        return PatchCheckRun(
            check_id=check.check_id,
            phase=phase,
            purpose=check.purpose,
            expected_exit_codes=check.expected_exit_codes,
            error=f"无法运行预登记检查: {exc}",
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )


def required_patch_checks(
    proposal: PatchProposal,
    checks: list[HarnessCheck],
) -> list[HarnessCheck]:
    requested = set(proposal.verification_check_ids)
    changed = set(proposal.changed_files)
    selected = []
    for check in checks:
        covered = set(check.covers_files)
        mandatory = bool(covered & changed) or (
            check.purpose == "regression" and not covered
        )
        if check.check_id in requested or mandatory:
            selected.append(check)
    return selected


def _file_digests(root: Path, files: list[str]) -> dict[str, str]:
    return {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in files
    }


def verify_patch_in_sandbox(
    proposal: PatchProposal,
    report: IncidentReport,
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    hard_timeout_seconds: int = 5,
) -> PatchVerificationResult:
    """重新校验、复制、基线运行、临时应用和修复后运行；不写正式项目。"""
    started = perf_counter()
    root = root.resolve()
    draft = PatchProposalDraft.model_validate(proposal.model_dump(
        exclude={"proposal_id", "status", "validation_errors"}
    ))
    current = validate_patch_draft(
        draft,
        report,
        root=root,
        manifest_path=manifest_path,
    )
    if current.status != "validated" or current.proposal_id != proposal.proposal_id:
        errors = current.validation_errors or ["提案内容或 proposal_id 已发生变化"]
        return PatchVerificationResult(
            proposal_id=proposal.proposal_id,
            status="rejected",
            validation_errors=errors,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
    before = _file_digests(root, proposal.changed_files)

    manifest, _digest = load_harness_manifest(manifest_path)
    checks = required_patch_checks(proposal, manifest.checks)
    required_ids = [item.check_id for item in checks]
    covered_files = {
        relative
        for check in checks
        for relative in check.covers_files
    }
    uncovered_files = sorted(set(proposal.changed_files) - covered_files)
    if uncovered_files:
        return PatchVerificationResult(
            proposal_id=proposal.proposal_id,
            status="rejected",
            required_check_ids=required_ids,
            validation_errors=[
                "以下修改文件没有任何预登记检查声明覆盖: "
                + ", ".join(uncovered_files)
            ],
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
    if not checks:
        return PatchVerificationResult(
            proposal_id=proposal.proposal_id,
            status="rejected",
            required_check_ids=[],
            validation_errors=["没有可用于验证该补丁的预登记 Harness 检查"],
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )

    temporary = Path(tempfile.mkdtemp(prefix="incident-patch-"))
    sandbox = temporary / "workspace"
    runs: list[PatchCheckRun] = []
    applied = False
    errors: list[str] = []
    cleaned = False
    try:
        sandbox.mkdir(parents=True)
        _copy_project(root, sandbox)
        for check in checks:
            runs.append(_run_check(check, sandbox, "baseline", hard_timeout_seconds))
        invalid_baselines = [
            run.check_id for run in runs
            if run.phase == "baseline"
            and run.purpose == "reproduction"
            and not run.success_criterion_met
        ]
        if invalid_baselines:
            errors.append(
                "补丁前无法稳定复现目标故障: " + ", ".join(invalid_baselines)
            )
        else:
            apply_validated_patch_to_sandbox(proposal, sandbox)
            applied = True
            for check in checks:
                runs.append(_run_check(check, sandbox, "patched", hard_timeout_seconds))
            failed = [
                run.check_id for run in runs
                if run.phase == "patched" and not run.success_criterion_met
            ]
            if failed:
                errors.append("补丁后检查未满足成功条件: " + ", ".join(failed))
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
        cleaned = not temporary.exists()

    unchanged = before == _file_digests(root, proposal.changed_files)
    if not unchanged:
        errors.append("正式工作区目标文件发生变化，已拒绝验证结果")
    if not cleaned:
        errors.append("临时隔离目录未能完全清理")
    status = "verified" if applied and not errors else "failed"
    return PatchVerificationResult(
        proposal_id=proposal.proposal_id,
        status=status,
        applied_in_sandbox=applied,
        workspace_unchanged=unchanged,
        sandbox_cleaned=cleaned,
        required_check_ids=required_ids,
        check_runs=runs,
        validation_errors=errors,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
