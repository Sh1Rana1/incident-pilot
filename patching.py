"""V13 Patch Proposal：跨服务商输出契约与确定性安全校验。"""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from harness import DEFAULT_MANIFEST_PATH, load_harness_manifest
from models import IncidentReport, PatchProposal, PatchProposalDraft


ROOT = Path(__file__).resolve().parent
MAX_CHANGED_FILES = 3
MAX_CHANGED_LINES = 120
MAX_CONTEXT_CHARS_PER_FILE = 16_000
ALLOWED_SUFFIXES = {".py"}
PROTECTED_PARTS = {
    ".git",
    ".venv",
    ".incident_cache",
    ".incident_reports",
    ".incident_state",
    "__pycache__",
    "evals",
    "fixtures",
    "checks",
}
PROTECTED_FILES = {
    "api.env",
    ".env",
    "harness.json",
    "harness.py",
    "patching.py",
    "patch_verification.py",
    "evaluation.py",
    "llm_judge.py",
    "benchmark.py",
    "experiments.py",
    "run_evals.py",
}
DIFF_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$"
)


def parse_patch_draft(content: str) -> PatchProposalDraft:
    """兼容纯 JSON、JSON 代码块或 JSON 前后的少量说明。"""
    stripped = content.strip()
    candidates = [stripped]
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            candidates.append("\n".join(lines[1:-1]).strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start:end + 1])
    last_error: ValidationError | None = None
    for candidate in dict.fromkeys(candidates):
        try:
            return PatchProposalDraft.model_validate_json(candidate)
        except ValidationError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def build_patch_source_context(
    report: IncidentReport,
    root: Path = ROOT,
) -> str:
    """只读取报告已经引用过的代码文件，为生成精确 diff 提供当前内容。"""
    paths = list(dict.fromkeys(
        item.file for item in report.evidence
        if item.source_type == "code" and item.file
    ))[:MAX_CHANGED_FILES]
    sections: list[str] = []
    for relative in paths:
        try:
            path = _resolve_candidate(relative, root)
            content = path.read_text(encoding="utf-8")[:MAX_CONTEXT_CHARS_PER_FILE]
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        numbered = "\n".join(
            f"{number}: {line}"
            for number, line in enumerate(content.splitlines(), 1)
        )
        sections.append(f"FILE {relative}\n{numbered}")
    return "\n\n".join(sections)


def build_patch_output_contract(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> str:
    """给不支持 json_schema 的服务商提供同一份严格输出契约。"""
    manifest, _digest = load_harness_manifest(manifest_path)
    checks = "\n".join(
        f"- {item.check_id} [{item.purpose}; "
        f"covers={','.join(item.covers_files) or 'global'}]: {item.description}"
        for item in manifest.checks
    )
    schema = json.dumps(
        PatchProposalDraft.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    example = json.dumps({
        "diagnosis_claim_ids": ["C1"],
        "changed_files": ["path/to/existing.py"],
        "unified_diff": (
            "diff --git a/path/to/existing.py b/path/to/existing.py\n"
            "--- a/path/to/existing.py\n+++ b/path/to/existing.py\n"
            "@@ -1,1 +1,1 @@\n-old line\n+new line"
        ),
        "rationale": "说明修改如何解决已验证 Claim",
        "risks": ["说明一个具体风险；确实没有时使用空数组"],
        "verification_check_ids": ["从下方清单选择一个真实 ID"],
    }, ensure_ascii=False, indent=2)
    return (
        "输出必须是单个 JSON 对象，并且只能有以下六个顶层字段；"
        "不得添加 type、patch_id、status、objective、reasoning、scope_guards、"
        "risk_notes、confidence 或 Markdown 代码围栏。\n\n"
        f"严格 JSON Schema：\n{schema}\n\n"
        f"格式示例（占位内容必须替换）：\n{example}\n\n"
        "verification_check_ids 只能从以下清单选择，至少选择一个：\n"
        f"{checks}"
    )


def validate_patch_draft(
    draft: PatchProposalDraft,
    report: IncidentReport,
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
) -> PatchProposal:
    """校验提案但绝不应用它；错误提案仍以 rejected 状态返回供审计。"""
    errors: list[str] = []
    claim_map = {item.claim_id: item for item in report.claims}
    if len(draft.diagnosis_claim_ids) != len(set(draft.diagnosis_claim_ids)):
        errors.append("diagnosis_claim_ids 不能重复")
    for claim_id in draft.diagnosis_claim_ids:
        claim = claim_map.get(claim_id)
        if claim is None:
            errors.append(f"诊断 Claim 不存在: {claim_id}")
        elif not claim.evidence_ids:
            errors.append(f"诊断 Claim 没有绑定 Evidence: {claim_id}")

    evidenced_files = {
        item.file for item in report.evidence
        if item.source_type == "code" and item.file
    }
    parsed_files, changed_lines, diff_errors = _parse_and_check_diff(
        draft.unified_diff,
        root,
    )
    errors.extend(diff_errors)
    declared_files = draft.changed_files
    if len(declared_files) != len(set(declared_files)):
        errors.append("changed_files 不能重复")
    if set(declared_files) != set(parsed_files):
        errors.append("changed_files 必须与 unified_diff 中的文件完全一致")
    if len(parsed_files) > MAX_CHANGED_FILES:
        errors.append(f"单个提案最多修改 {MAX_CHANGED_FILES} 个文件")
    if changed_lines > MAX_CHANGED_LINES:
        errors.append(f"单个提案最多增删 {MAX_CHANGED_LINES} 行")
    for relative in parsed_files:
        if relative not in evidenced_files:
            errors.append(f"修改文件没有出现在诊断代码 Evidence 中: {relative}")

    try:
        manifest, _digest = load_harness_manifest(manifest_path)
        known_checks = {item.check_id for item in manifest.checks}
        if len(draft.verification_check_ids) != len(
            set(draft.verification_check_ids)
        ):
            errors.append("verification_check_ids 不能重复")
        for check_id in draft.verification_check_ids:
            if check_id not in known_checks:
                errors.append(f"验证检查未在 Harness 中登记: {check_id}")
    except ValueError as exc:
        errors.append(f"无法验证 Harness 检查: {exc}")

    proposal_id = "patch-" + hashlib.sha256(
        draft.model_dump_json().encode("utf-8")
    ).hexdigest()[:12]
    return PatchProposal(
        **draft.model_dump(),
        proposal_id=proposal_id,
        status="rejected" if errors else "validated",
        validation_errors=list(dict.fromkeys(errors)),
    )


def apply_validated_patch_to_sandbox(
    proposal: PatchProposal,
    sandbox_root: Path,
) -> None:
    """只在显式临时副本中应用已验证 diff，拒绝把仓库根目录作为目标。"""
    resolved_root = sandbox_root.resolve()
    if resolved_root == ROOT.resolve():
        raise ValueError("V13 禁止把 Patch Proposal 直接应用到正式工作区")
    if proposal.status != "validated":
        raise ValueError("只有 validated Patch Proposal 才能进入隔离验证")
    _files, _changed, errors = _parse_and_check_diff(
        proposal.unified_diff,
        resolved_root,
    )
    if errors:
        raise ValueError("隔离副本中的补丁上下文校验失败: " + "；".join(errors))

    lines = proposal.unified_diff.replace("\r\n", "\n").splitlines()
    index = 0
    while index < len(lines):
        header = DIFF_HEADER.fullmatch(lines[index])
        if header is None:
            raise ValueError(f"无法解析 diff 第 {index + 1} 行")
        relative = header.group(2)
        target = _resolve_candidate(relative, resolved_root)
        index += 1
        section: list[str] = []
        while index < len(lines) and not lines[index].startswith("diff --git "):
            section.append(lines[index])
            index += 1
        _apply_file_section(target, relative, section)


def _apply_file_section(target: Path, relative: str, lines: list[str]) -> None:
    content = target.read_text(encoding="utf-8")
    source = content.splitlines()
    output: list[str] = []
    source_cursor = 0
    try:
        cursor = lines.index(f"+++ b/{relative}") + 1
    except ValueError as exc:
        raise ValueError(f"缺少隔离应用所需的 +++ 文件头: {relative}") from exc

    while cursor < len(lines):
        match = HUNK_HEADER.fullmatch(lines[cursor])
        if match is None:
            cursor += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        start_index = old_start - 1 if old_count else old_start
        output.extend(source[source_cursor:start_index])
        source_cursor = start_index
        cursor += 1
        while cursor < len(lines) and not lines[cursor].startswith("@@ "):
            line = lines[cursor]
            if line == "\\ No newline at end of file":
                cursor += 1
                continue
            marker, value = line[0], line[1:]
            if marker == " ":
                output.append(value)
                source_cursor += 1
            elif marker == "-":
                source_cursor += 1
            elif marker == "+":
                output.append(value)
            cursor += 1
    output.extend(source[source_cursor:])
    rendered = "\n".join(output)
    if content.endswith(("\n", "\r")):
        rendered += "\n"
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(rendered)


def _resolve_candidate(relative: str, root: Path) -> Path:
    if not relative or "\\" in relative:
        raise ValueError(f"补丁路径必须是 POSIX 项目相对路径: {relative}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ValueError(f"补丁路径不能离开项目根目录: {relative}")
    lower_parts = {part.lower() for part in pure.parts}
    if lower_parts & PROTECTED_PARTS:
        raise ValueError(f"补丁路径属于受保护目录: {relative}")
    lower_name = pure.name.lower()
    if lower_name in PROTECTED_FILES or lower_name.startswith("test_"):
        raise ValueError(f"补丁不能修改受保护文件: {relative}")
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"V13 只允许提出 Python 源文件修改: {relative}")
    path = (root / Path(*pure.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"补丁路径不能离开项目根目录: {relative}") from exc
    if not path.is_file():
        raise ValueError(f"V13 不能创建或删除文件，目标必须已经存在: {relative}")
    return path


def _parse_and_check_diff(
    unified_diff: str,
    root: Path,
) -> tuple[list[str], int, list[str]]:
    lines = unified_diff.replace("\r\n", "\n").splitlines()
    parsed_files: list[str] = []
    changed_lines = 0
    errors: list[str] = []
    index = 0
    if not lines or not lines[0].startswith("diff --git "):
        return [], 0, ["unified_diff 必须以 diff --git 标准文件头开始"]
    while index < len(lines):
        header = DIFF_HEADER.fullmatch(lines[index])
        if header is None:
            errors.append(f"第 {index + 1} 行不是合法 diff --git 文件头")
            break
        old_path, new_path = header.groups()
        if old_path != new_path:
            errors.append("V13 不允许重命名文件")
        relative = new_path
        parsed_files.append(relative)
        try:
            source_path = _resolve_candidate(relative, root)
            source_lines = source_path.read_text(encoding="utf-8").splitlines()
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            errors.append(str(exc))
            source_lines = []
        index += 1
        section: list[str] = []
        while index < len(lines) and not lines[index].startswith("diff --git "):
            section.append(lines[index])
            index += 1
        section_changed, section_errors = _validate_file_section(
            relative,
            section,
            source_lines,
        )
        changed_lines += section_changed
        errors.extend(section_errors)
    if len(parsed_files) != len(set(parsed_files)):
        errors.append("同一个文件不能出现多个 diff 区块")
    if changed_lines == 0:
        errors.append("补丁必须至少增加或删除一行")
    return parsed_files, changed_lines, errors


def _validate_file_section(
    relative: str,
    lines: list[str],
    source_lines: list[str],
) -> tuple[int, list[str]]:
    errors: list[str] = []
    forbidden = (
        "new file mode", "deleted file mode", "old mode", "new mode",
        "rename from", "rename to", "copy from", "copy to",
        "similarity index", "dissimilarity index", "Binary files",
        "GIT binary patch",
    )
    if any(line.startswith(forbidden) for line in lines):
        errors.append(
            f"V13 不允许创建、删除、重命名、复制、改权限或修改二进制文件: "
            f"{relative}"
        )
    try:
        old_header = lines.index(f"--- a/{relative}")
        new_header = lines.index(f"+++ b/{relative}")
    except ValueError:
        return 0, errors + [f"缺少标准 ---/+++ 文件头: {relative}"]
    if new_header != old_header + 1:
        errors.append(f"--- 与 +++ 文件头必须相邻: {relative}")
    cursor = new_header + 1
    previous_end = 0
    changed = 0
    hunk_count = 0
    while cursor < len(lines):
        match = HUNK_HEADER.fullmatch(lines[cursor])
        if match is None:
            cursor += 1
            continue
        hunk_count += 1
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_count = int(match.group(4) or "1")
        if old_start < previous_end:
            errors.append(f"diff hunk 顺序重叠: {relative}")
        cursor += 1
        old_values: list[str] = []
        actual_new_count = 0
        while cursor < len(lines) and not lines[cursor].startswith("@@ "):
            line = lines[cursor]
            if line.startswith("diff --git "):
                break
            if line == "\\ No newline at end of file":
                cursor += 1
                continue
            if not line or line[0] not in {" ", "+", "-"}:
                errors.append(f"hunk 包含非法行: {relative}:{cursor + 1}")
                cursor += 1
                continue
            marker, value = line[0], line[1:]
            if marker in {" ", "-"}:
                old_values.append(value)
            if marker in {" ", "+"}:
                actual_new_count += 1
            if marker in {"+", "-"}:
                changed += 1
            cursor += 1
        if len(old_values) != old_count or actual_new_count != new_count:
            errors.append(f"hunk 行数与 @@ 声明不一致: {relative}")
        source_start = max(old_start - 1, 0)
        if source_lines[source_start:source_start + old_count] != old_values:
            errors.append(f"补丁上下文与当前文件不一致，无法安全应用: {relative}")
        previous_end = old_start + old_count
    if hunk_count == 0:
        errors.append(f"文件没有合法 @@ hunk: {relative}")
    return changed, errors
