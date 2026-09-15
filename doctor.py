"""V12.1.1 本地启动自检；不连接模型服务，也不输出 API Key。"""

import json
import sys
import sqlite3
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = ROOT / ".incident_state" / "incident_pilot.sqlite3"
REQUIRED_PACKAGES = (
    "openai",
    "python-dotenv",
    "pydantic",
    "langgraph",
    "langgraph-checkpoint-sqlite",
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)


def run_doctor(
    root: Path = ROOT,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> DoctorReport:
    """检查本地启动条件；不会创建模型客户端或发起网络请求。"""
    checks: list[DoctorCheck] = []
    python_ok = sys.version_info >= (3, 10)
    checks.append(DoctorCheck(
        "Python",
        python_ok,
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        + ("" if python_ok else "；需要 3.10 或更高版本"),
    ))

    missing: list[str] = []
    installed: list[str] = []
    for package in REQUIRED_PACKAGES:
        try:
            installed.append(f"{package}={version(package)}")
        except PackageNotFoundError:
            missing.append(package)
    checks.append(DoctorCheck(
        "Python 依赖",
        not missing,
        ", ".join(installed) if not missing else "缺少: " + ", ".join(missing),
    ))

    if missing:
        # 保持 doctor 自身只有标准库依赖；即使 dotenv/langgraph 未安装，
        # 仍能给出 api.env 的基础诊断，而不是在导入阶段崩溃。
        try:
            values = _read_env_file(root / "api.env")
            absent = [name for name in ("API_KEY", "MODEL") if not values.get(name)]
            if absent:
                raise RuntimeError(f"api.env 缺少配置: {', '.join(absent)}")
            checks.append(DoctorCheck(
                "api.env",
                True,
                f"model={values['MODEL']}, 基础格式有效；安装依赖后将执行完整校验",
            ))
        except Exception as exc:
            checks.append(DoctorCheck("api.env", False, str(exc)))
    else:
        try:
            from config import load_config

            config = load_config(root)
            checks.append(DoctorCheck(
                "api.env",
                True,
                f"model={config.model}, output_mode={config.output_mode}, "
                f"runtime={'on' if config.runtime_tools_enabled else 'off'}",
            ))
        except Exception as exc:
            checks.append(DoctorCheck("api.env", False, str(exc)))

    try:
        manifest_path = root / "harness.json"
        if missing:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if raw_manifest.get("version") != 1 or not raw_manifest.get("checks"):
                raise ValueError("需要 version=1 且 checks 不能为空")
            detail = (
                f"version=1, checks={len(raw_manifest['checks'])}；"
                "安装依赖后将执行完整安全校验"
            )
        else:
            from harness import load_harness_manifest

            manifest, digest = load_harness_manifest(manifest_path)
            detail = (
                f"version={manifest.version}, checks={len(manifest.checks)}, "
                f"sha256={digest[:12]}"
            )
        checks.append(DoctorCheck("Safe Test Harness", True, detail))
    except Exception as exc:
        checks.append(DoctorCheck("Safe Test Harness", False, str(exc)))

    try:
        if missing:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database_path)
            connection.execute("SELECT 1").fetchone()
            connection.close()
        else:
            from session_store import SessionStore

            with SessionStore(database_path):
                pass
        checks.append(DoctorCheck("SQLite 状态库", True, str(database_path.resolve())))
    except Exception as exc:
        checks.append(DoctorCheck("SQLite 状态库", False, str(exc)))

    return DoctorReport(tuple(checks))


def print_doctor_report(report: DoctorReport) -> None:
    print("\nIncidentPilot 本地自检（不会调用模型 API）")
    for item in report.checks:
        marker = "通过" if item.ok else "失败"
        print(f"[{marker}] {item.name}：{item.detail}")
    print("\n自检通过，可以开始调查。" if report.ok else "\n自检未通过，请先修复失败项。")


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    return values


if __name__ == "__main__":
    doctor_report = run_doctor()
    print_doctor_report(doctor_report)
    raise SystemExit(0 if doctor_report.ok else 1)
