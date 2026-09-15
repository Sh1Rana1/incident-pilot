"""V12.1.1 统一数据模型：诊断证据、只读补丁提案、会话与指标。"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolResult(StrictModel):
    ok: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, data: Any, **meta: Any) -> "ToolResult":
        return cls(ok=True, data=data, error=None, meta=meta)

    @classmethod
    def failure(cls, error: str, **meta: Any) -> "ToolResult":
        return cls(ok=False, data=None, error=error, meta=meta)


SourceType = Literal["code", "documentation", "git", "runtime", "unknown"]


class ObservedSource(StrictModel):
    source_type: SourceType
    file: str = ""
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    chunk_id: Optional[str] = None
    commit_hash: Optional[str] = None
    runtime_id: Optional[str] = None


class ToolObservation(StrictModel):
    observation_id: str
    tool_call_id: str
    step: int
    tool_name: str
    arguments: dict[str, Any]
    ok: bool
    repeated: bool = False
    sources: list[ObservedSource] = Field(default_factory=list)
    error: Optional[str] = None
    result_sha256: str
    result_excerpt: str
    duration_ms: float


HypothesisStatus = Literal["unverified", "supported", "rejected", "confirmed"]


class InvestigationAction(StrictModel):
    tool_name: str = Field(description="下一步只选择一个最有区分度的工具")
    purpose: str = Field(description="为什么此工具能区分当前候选假设")
    supports_if: str = Field(description="看到什么结果会支持该假设")
    rejects_if: str = Field(description="看到什么结果会否定该假设")


class DiagnosticHypothesis(StrictModel):
    hypothesis_id: str = Field(description="调查内唯一假设 ID，例如 H1")
    statement: str = Field(description="可以通过工具证据证实或证伪的根因假设")
    status: HypothesisStatus
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_observation_ids: list[str] = Field(default_factory=list)
    contradicting_observation_ids: list[str] = Field(default_factory=list)
    next_action: Optional[InvestigationAction] = Field(
        default=None,
        description="结构化的下一项调查动作；已确认或否定时可为 null",
    )


class HypothesisUpdate(StrictModel):
    hypotheses: list[DiagnosticHypothesis] = Field(
        min_length=1,
        max_length=6,
        description="当前完整假设集合，而不是仅包含本轮变化",
    )


class HumanReviewRequest(StrictModel):
    reason: str
    message: str
    model_call_count: int
    tool_call_count: int
    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    allowed_actions: list[
        Literal["continue", "summarize", "approve", "deny", "cancel"]
    ]


class Evidence(StrictModel):
    evidence_id: str = Field(description="报告内唯一证据 ID，例如 E1")
    observation_id: str = Field(description="产生这条证据的真实工具 Observation ID")
    source_type: SourceType = Field(
        description="证据来源类型"
    )
    file: str = Field(description="证据所在的项目相对路径；未知时填空字符串")
    line_start: Optional[int] = Field(description="证据起始行；不适用时填 null")
    line_end: Optional[int] = Field(description="证据结束行；不适用时填 null")
    commit_hash: Optional[str] = Field(description="Git 证据的提交哈希；不适用时填 null")
    runtime_id: Optional[str] = Field(
        description="Runtime 证据的系统运行编号；不适用时填 null",
    )
    description: str = Field(description="这条证据说明了什么")


class DiagnosticClaim(StrictModel):
    claim_id: str = Field(description="报告内唯一结论 ID，例如 C1")
    statement: str = Field(description="一项可由证据支持的诊断结论")
    evidence_ids: list[str] = Field(description="支持该结论的证据 ID")


class IncidentReport(StrictModel):
    summary: str = Field(description="一句话概括调查结果")
    root_cause: str = Field(description="根因；证据不足时明确说明尚不能确定")
    claims: list[DiagnosticClaim] = Field(description="Claim—Evidence Ledger")
    evidence: list[Evidence] = Field(description="支持结论的证据列表")
    suggested_fixes: list[str] = Field(description="建议的修复步骤")
    confidence: Literal["low", "medium", "high"]


class PatchProposalDraft(StrictModel):
    """模型生成的候选内容；不允许模型声明验证状态或提案 ID。"""

    diagnosis_claim_ids: list[str] = Field(min_length=1, max_length=10)
    changed_files: list[str] = Field(min_length=1, max_length=3)
    unified_diff: str = Field(min_length=1, max_length=50_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    risks: list[str] = Field(max_length=10)
    verification_check_ids: list[str] = Field(min_length=1, max_length=5)


class PatchProposal(PatchProposalDraft):
    """经过本地确定性规则验证的只读补丁提案。"""

    proposal_id: str
    status: Literal["validated", "rejected"]
    validation_errors: list[str] = Field(default_factory=list)


class PatchCheckRun(StrictModel):
    """V13 隔离工作区中一次预登记检查的结构化结果。"""

    check_id: str
    phase: Literal["baseline", "patched"]
    purpose: Literal["reproduction", "regression"]
    exit_code: Optional[int] = None
    expected_exit_codes: list[int] = Field(default_factory=list)
    expectation_met: bool = False
    success_criterion_met: bool = False
    passed_count: int = 0
    failed_count: int = 0
    failed_tests: list[str] = Field(default_factory=list)
    timed_out: bool = False
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0


class PatchVerificationResult(StrictModel):
    """候选补丁在临时隔离副本中的验证结果；不代表正式工作区已修改。"""

    proposal_id: str
    status: Literal["verified", "failed", "rejected", "denied"]
    applied_in_sandbox: bool = False
    workspace_unchanged: bool = True
    sandbox_cleaned: bool = True
    required_check_ids: list[str] = Field(default_factory=list)
    check_runs: list[PatchCheckRun] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


MemoryStatus = Literal["pending", "approved", "rejected"]


class IncidentMemory(StrictModel):
    """从已验证调查中提取的历史线索；它不是当前调查证据。"""

    memory_id: str
    source_thread_id: str
    status: MemoryStatus
    exception_types: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    summary: str
    root_cause: str
    resolution: list[str] = Field(default_factory=list)
    source_confidence: Literal["medium", "high"]
    created_at: str
    updated_at: str
    approved_at: Optional[str] = None


class IncidentMemoryMatch(StrictModel):
    memory: IncidentMemory
    score: float = Field(ge=0.0)


class RunMetrics(StrictModel):
    tool_profile: str = Field(description="本次运行使用的工具 Profile")
    model_call_count: int = Field(description="包括强制总结和格式修复在内的模型请求总数")
    investigation_step_count: int = Field(description="允许使用工具的调查阶段模型请求数")
    tool_call_count: int = Field(description="模型提出的工具调用总数，包括被拦截的重复调用")
    unique_tool_call_count: int = Field(description="实际执行的唯一外部工具调用数")
    repeated_tool_call_count: int = Field(description="被重复调用保护拦截的次数")
    observation_count: int = Field(description="包括失败与重复调用在内的 Observation 数量")
    successful_observation_count: int = Field(description="成功执行且非重复的 Observation 数量")
    synthesis_used: bool = Field(description="是否使用了无工具的强制总结节点")
    format_repair_used: bool = Field(
        default=False,
        description="是否执行过最后一次无工具格式修复",
    )
    early_stopped: bool = Field(
        default=False,
        description="是否因假设证据充分而在硬预算前提前总结",
    )
    hypothesis_count: int = Field(default=0)
    confirmed_hypothesis_count: int = Field(default=0)
    human_review_count: int = Field(default=0)
    protected_access_attempt_count: int = Field(default=0)
    input_token_count: int = Field(default=0)
    output_token_count: int = Field(default=0)
    total_token_count: int = Field(default=0)
    context_compaction_count: int = Field(default=0)
    unreferenced_successful_observation_count: int = Field(default=0)
    observation_utilization_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    post_confirmation_tool_call_count: int = Field(default=0)
    runtime_call_count: int = Field(default=0)
    successful_runtime_call_count: int = Field(default=0)
    runtime_timeout_count: int = Field(default=0)
    runtime_approval_count: int = Field(default=0)
    runtime_denial_count: int = Field(default=0)
    runtime_replay_count: int = Field(default=0)
    recalled_memory_count: int = Field(default=0)
    patch_requested: bool = Field(default=False)
    patch_proposal_generated: bool = Field(default=False)
    patch_proposal_valid: bool = Field(default=False)
    patch_verification_requested: bool = Field(default=False)
    patch_verification_approval_count: int = Field(default=0)
    patch_verification_check_count: int = Field(default=0)
    patch_verified: bool = Field(default=False)
    tool_names: list[str] = Field(description="按请求顺序记录的工具名")
    stop_reason: str
    duration_ms: float


class AgentRunResult(StrictModel):
    report: IncidentReport
    metrics: RunMetrics
    observations: list[ToolObservation] = Field(default_factory=list)
    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    validation_errors: list[str] = Field(
        default_factory=list,
        description="本次运行历次报告格式、假设准备度和来源验证错误",
    )
    patch_proposal: Optional[PatchProposal] = None
    patch_validation_errors: list[str] = Field(default_factory=list)
    patch_verification: Optional[PatchVerificationResult] = None
