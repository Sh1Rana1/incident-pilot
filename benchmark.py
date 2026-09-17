"""Benchmark 划分清单：固定案例用途，避免开发阶段误用 hidden set。"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from models import StrictModel


BenchmarkSplit = Literal["development", "hidden", "challenge", "runtime", "all"]


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
