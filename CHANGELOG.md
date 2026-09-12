# IncidentPilot 版本记录

本文件只记录版本演进、行为变化和迁移注意事项。当前版本的安装、使用、架构与完整原理统一写在 `README.md`。

## 文档维护约定

以后每次发布或完成一个版本，必须同步维护两个文件：

1. `README.md`：更新为新版本当前真实存在的能力、接口、命令、限制与测试结果，不保留已经失效的旧实现说明；
2. `CHANGELOG.md`：新增一个版本章节，记录新增、修改、修复、测试变化和兼容性影响。

如果只是修正文案且不改变程序行为，可以只更新文档；任何代码、配置、命令、数据结构或安全边界变化都必须同步更新两份文件。

---

## V8.1.1：Evidence Preservation 与 Hypothesis Update Gate

### 修复

- 修复 `documentation_required` 真实实验中已经取得30秒代码配置与10秒供应商文档，却因未写入假设和普通上下文窗口淘汰而无法生成报告的问题。
- 新增 `hypothesis_update_required` 控制门：已有假设时，一轮产生新成功 Observation 后，下一轮必须先成功更新假设；此前提出的外部工具调用会被拒绝，从控制流层阻止重复搜索和证据闲置。
- 强制总结和格式修复改用证据保全上下文，保留全部带真实来源的成功 Observation、全部假设引用与最近两条失败结果；普通调查仍使用 V8.1 的低成本窗口。
- 报告解析兼容纯 JSON、Markdown JSON 代码块以及 JSON 前后的少量说明文字，仍由同一 Pydantic Schema 严格验证。
- Pydantic 错误不再只记录数量，改为保存字段路径和具体错误；历次格式、假设准备度与 Provenance 错误进入 `AgentRunResult.validation_errors` 和 Evaluation JSON。
- 最终修复仍失败时，优先依据最高置信度的 supported/confirmed 假设及其真实 Observation 构造有来源的降级报告；`stop_reason` 仍保留 `invalid_synthesis`，不会掩盖失败。
- 修正空 Evidence 的引用有效率：没有提交任何引用时现在记为 0%，不再显示误导性的 100%。

### 成本与正确性

- 控制门在模型请求中提前提示先更新假设，只有模型忽略提示时才由执行层拒绝外部调用，避免正常路径无故增加请求。
- 最终证据保全只增加带来源的成功 Observation，不重新发送目录列表和完整历史；解决关键证据丢失的同时继续控制输入 Token。
- 成本优化仍以诊断通过为前提，失败运行不能作为“Token 降低”的验收数据。

### 验证

- 新增最终证据保全、假设更新控制门和宽容 JSON 外壳解析回归测试，并扩展验证错误持久化测试。
- 94 项离线测试全部通过；未调用真实模型，未产生 API 费用。

### 兼容性

- 现有命令和 `api.env` 无需修改；`AgentRunResult` 只新增带默认值的 `validation_errors` 字段。
- Evaluation JSON 的每个 Attempt 新增 `validation_errors[]`，旧报告仍可读取，但字段集合与新报告不同。

---

## V8.1：Context Budgeting 与 Investigation Efficiency

### 新增

- 新增 `context_manager.py`。完整 LangGraph 消息和 Observation 继续保存在 Checkpoint，但每次模型请求只发送原始 System/User、当前假设、全部已引用 Observation 和最近 4 条未引用 Observation。
- 每条压缩 Observation 保留系统 ID、轮次、工具、参数、状态与精确来源，结果摘要最多 700 字符；压缩请求不再携带旧的 Assistant/Tool 调用对，避免悬空 `tool_call_id` 和重复输入。
- 新增结构化 `InvestigationAction`，未确认假设必须声明下一工具、调查目的、支持条件和否定条件。
- 新增 `MAX_TOOLS_PER_STEP`，默认每轮最多执行 3 个外部工具。超额请求返回 `per_step_tool_limit`，下一轮可按信息增益重新规划；总工具预算仍独立生效。
- `RunMetrics` 新增上下文压缩次数、未引用成功 Observation 数、Observation 利用率和确认根因后的额外工具调用数。

### 成本控制

- 上下文压缩减少早期大段工具结果在后续每个模型请求中的重复传输；证据账本本身不删除，因此不会牺牲本地审计能力换取费用。
- 单轮工具上限控制调查宽度，总模型/工具硬预算控制最坏情况，confirmed 假设的独立证据 Gate 控制停止时机。
- Prompt 要求一次只规划一项最高信息增益动作，并按 traceback 直读文件、符号搜索、供应商约束查文档、回归线索查 Git 的顺序选择工具。
- 评测终端和 JSON 增加“利用/压缩”、未引用 Observation 与确认后调用指标，能够区分“答对了”和“是否高效地答对”。
- 超过 3 次真实调查仍需 `--yes`；本次开发只运行模拟模型的离线测试，没有消耗 API Token。

### 兼容性与限制

- `run_agent()`、`run_agent_detailed()` 和现有 Profile/评测命令保持兼容；旧 `api.env` 可继续使用，`MAX_TOOLS_PER_STEP` 缺省为 3。
- `DiagnosticHypothesis.next_action` 从自由文本升级为结构化对象。直接构造该模型的外部调用方需要迁移字段格式。
- 压缩是确定性选择策略，不是语义摘要模型；极长 Observation 的次要细节可能不再发送给模型，但完整消息仍保存在当前进程的 Checkpoint。
- 具体 Token 节省取决于模型服务的 usage 统计，需要用相同 Case 做真实前后对照；离线测试只验证行为和边界，不声称固定节省比例。

### 验证

- 新增上下文选择、摘要截断、修复上下文、结构化动作和单轮工具上限测试。
- 89 项离线测试全部通过；未调用真实模型，未产生 API 费用。

---

## V8：Hypothesis-Driven Investigation 与 Human-in-the-loop

### 新增

- 新增 `DiagnosticHypothesis`：保存候选根因、`unverified/supported/rejected/confirmed` 状态、置信度、支持 Observation、反证与下一步动作。
- 新增内部控制工具 `update_hypotheses`。它随所有 Tool Profile 暴露，但不读取工作区、不进入外部工具注册器，也不能生成可用于 Evidence 的 Observation。
- 新增 `hypotheses.py`，确定性校验假设 ID、状态与 Observation 引用；失败或不存在的 Observation 不能支持或否定假设。
- 新增证据充分度 Gate：置信度至少 0.8 的 confirmed 假设必须获得至少两项成功 Observation，且来自不同来源类型或不同文件，才允许提前总结。
- high 报告必须先形成 confirmed 假设，medium 报告必须至少形成 supported 假设；low 报告仍允许在证据不足时结束。
- 多个高置信度 confirmed 假设同时存在时标记为冲突，并在交互模式进入人工决策。
- 使用 LangGraph 原生 `interrupt()`、`InMemorySaver` 和 `Command(resume=...)` 实现同一进程内暂停与恢复。
- CLI 人工决策支持继续调查、立即总结和取消；取消不会再次调用模型。
- 新增模型调用、工具调用双硬预算，以及服务商 usage 中的输入、输出和总 Token 统计。
- `RunMetrics` 新增格式修复、早停、假设、人工确认、保护路径尝试和 Token 指标；`AgentRunResult` 与评测 JSON 持久化最终假设集合。

### 成本与安全

- 模型硬预算为强制总结和最后一次格式修复预留请求，工具预算在执行层拦截并行超额调用。
- `main.py` 达到模型/工具软阈值、访问受保护路径或出现冲突假设时触发 HITL；Evaluation 默认关闭 HITL，避免无人批处理阻塞。
- README 明确区分交互式 HITL 与无人值守 Evaluation，并给出低阈值演示方式。
- `run_evals.py` 新增费用保护：超过 3 次真实 Agent 调查必须显式使用 `--yes`，54 次稳定性实验不再能被普通烟雾测试命令误触发。
- HITL 不能放行 `evals`、fixture、缓存或敏感文件，只能决定调查控制流。

### Evaluation

- 逐次输出新增 confirmed 假设数、早停与 Token；Profile 聚合新增假设、早停、人工确认、保护路径、Token 和格式修复指标。
- 修正早停口径：只有在调查轮数、模型与工具硬预算之前因证据充分而总结才记为早停；最后预算轮确认不再虚报效率收益。
- 将原先含混的“格式兜底”拆成格式修复与最终确定性兜底。
- 每个评测 Attempt 同时保存完整 `observations[]` 与 `hypotheses[]`，支持事后审计。

### 兼容性与限制

- `run_agent()` 仍返回 `IncidentReport`；V7 调用方式不变。高级调用方可在 `run_agent_detailed()` 中设置模型/工具预算、启用 HITL 并提供 review handler。
- `api.env` 新增四个可选预算字段；旧配置不需要修改，缺省值分别为 10、20、5、10。
- 当前 Checkpointer 仍为内存实现，只支持当前 Python 进程内恢复；跨进程恢复留给后续持久化版本。
- 确定性证据充分度是工程启发式，尚不能替代对 Claim 与 Evidence 语义蕴含关系的判断。

### 验证

- 新增假设引用拒绝、单证据不早停、独立来源早停、冲突检测、原生 interrupt/resume 和评测费用保护测试。
- 84 项离线测试全部通过；未调用真实模型，未产生 API 费用。

---

## V7：Evidence-Driven Diagnosis

### 新增

- 新增 `provenance.py`，负责从工具结果提取真实来源并验证最终报告的证据出处。
- 每次工具调用生成系统控制的 `ToolObservation`，包含 Observation ID、Tool Call ID、调查轮次、参数、成功状态、重复标记、来源范围、结果 SHA-256、摘要和耗时。
- 工具结果的 `meta` 会返回 `observation_id`，供模型在最终报告中绑定来源。
- 新增 `ObservedSource`，统一表示代码行、运行日志、RAG Chunk、Git Diff Hunk 和 Git Commit。
- 新增 `DiagnosticClaim`，最终报告使用 Claim—Evidence Ledger 显式描述“哪条证据支持哪项结论”。
- `Evidence` 新增 `evidence_id`、`observation_id`、`line_start`、`line_end` 和 `commit_hash`。
- `AgentRunResult` 新增完整 `observations`；`RunMetrics` 新增 Observation 总数和成功数。

### 来源验证

- 报告进入完成状态前会同时经过 Pydantic Schema 和 Provenance Validator。
- 拒绝不存在或失败的 Observation、未观察文件、越界行号、来源类型不匹配和伪造 Git Commit。
- Git 短哈希可以与 `git_log` Observation 中的完整哈希匹配，不再需要把仓库目录伪装成文件证据。
- Claim 必须引用真实 Evidence；不允许重复 ID、缺失 Evidence 或未被 Claim 使用的游离证据。
- 来源验证失败会把具体错误返回模型重试；无工具格式修复仍保留。

### Evaluation

- 新增 Evidence Observation 落地率、Claim 覆盖率和 Provenance 违规数。
- 文档命中现在逐条验证绑定的 `retrieve_docs` Observation 确实返回了目标文档，而不是只检查是否调用过 RAG。
- V7 硬通过条件加入 100% Evidence 落地、100% Claim 覆盖、零 Provenance 违规和正常完成状态。
- 终端逐次结果和 Profile 汇总新增“落地、Claim、违规”列。
- 根因关键词匹配纳入 `claims[].statement`。Claim 是 V7 的正式诊断结论，精确数值写在 Claim 中不再被误判为缺失；修复建议和证据描述仍不参与匹配。
- 评测 JSON 的每个 `attempts[]` 现在持久化完整 `observations[]`，支持实验结束后独立复核 Evidence 来源；旧报告只有运行时落地结果，无法事后重算 Provenance。

### 兼容性

- `IncidentReport` JSON Schema 有意升级；旧报告中的单个 `line` 字段需要迁移为 `line_start/line_end`，并补充 Claim、Evidence ID 与 Observation ID。
- `run_agent()` 仍只返回 `IncidentReport`；需要调查轨迹和指标时使用 `run_agent_detailed()`。
- README 补充 Windows Execution Policy 排错说明；无需激活虚拟环境，可直接使用 `.\.venv\Scripts\python.exe` 运行项目。

### 验证

- 新增 Observation ID 回传、伪造 Observation 拒绝、越界行号、Git Commit 绑定、缺失 Evidence 和评测落地指标测试。
- 72 项离线测试全部通过。
- 未自动运行真实模型实验，避免未经确认产生 API 费用。

---

## V6.1.2：评测基础设施隔离

### 修复

- 将 `evaluation.py`、`experiments.py`、`run_evals.py` 及对应测试设为 Agent 内部文件，避免模型从测试源码读取 `root_cause_keywords` 等隐藏标准答案。
- `read_file`、`search_code` 和 `list_files` 均执行该文件级隔离。
- `git_diff` 改为只接受单个现有文件，拒绝目录和仓库根目录，避免通过宽范围 Diff 绕过文档与评测隔离。

### 验证

- 新增评测基础设施列表、读取、搜索隔离和宽范围 Git Diff 拒绝测试。

---

## V6.1.1：评分与收尾稳定性修正

### 修复

- `documentation_required` 的数值标准由裸字符串 `30`、`10` 改为 `30 秒`、`10 秒`，避免“第 10 行”被误算成供应商 10 秒上限。
- 第一次完全重复工具调用现在只返回去重反馈，并给模型一轮纠正机会；同一次调查第二次重复才强制总结。
- 强制总结未通过 Pydantic 验证时，新增一次不带工具的严格 JSON 格式修复；修复仍失败才进入低置信度兜底。
- 案例通过条件显式要求 `stop_reason=completed`，避免异常结束的报告被意外判为通过。

### 可观测性

- `CaseScores` 新增 `failure_reasons`，记录缺失根因关键词、代码证据不足、无效引用和异常停止原因。
- 终端汇总新增“失败原因”区域，不再需要先打开完整 JSON 才能判断失败类型。

### 验证

- 新增首次/二次重复调用、强制总结格式修复、带单位数值评分和失败原因展示测试。
- 真实模型实验需由用户主动运行，以免自动产生 API 费用。

---

## V6.1：实验隔离与高区分度案例

### 修复

- 修复 `code_only` 可以通过 `read_file`、`search_code` 和 `list_files` 直接访问 RAG 文档的问题。
- Profile 现在除工具 Schema 和执行白名单外，还实施路径级隔离：所有 Markdown 都不能由通用文件工具访问；已索引的 `knowledge/` 与 `demo_app/docs/` 只能通过 `retrieve_docs` 获取。
- `demo_app/fixtures/` 被设为 Agent 内部目录，用于模拟不可检查源码的外部系统。
- 文档命中只有在本次运行实际调用 `retrieve_docs` 时才计分，避免猜中文档路径被误算成 RAG 贡献。
- 删除三个基础故障源码中直接写明答案的 `BUG-xxx` 注释，减少答案泄漏与天花板效应。

### 新增

- 新增 `documentation_required`：只有供应商契约文档记录 Acme Notify v2 的 `timeout_seconds <= 10` 约束。
- 新增 `git_regression`：要求通过 Git 历史定位确实引入 Demo 故障代码的提交 `61932b9`。
- 新增 `misleading_documentation`：加入已废弃的连接池扩容建议，测试 RAG 面对冲突材料时是否仍遵循当前代码和 Runbook。
- 新增 webhook 故障运行入口、日志、供应商文档和不可见外部网关夹具。
- 评测案例总数由 3 个增加到 6 个，其中 4 个可以通过 `demo_app.run_case` 稳定复现。

### 验证

- 新增 Profile 文档读取拒绝、搜索隐藏、目录隐藏、外部夹具隔离、RAG 归因评分和 webhook 故障复现测试。
- 59 项离线测试全部通过。
- 未自动运行真实模型对照实验，避免未经确认产生 API 费用。

---

## V6：工具消融实验与稳定性评测

### 新增

- 新增 `tool_profiles.py`，定义三种工具 Profile：
  - `code_only`：`list_files`、`search_code`、`read_file`；
  - `code_rag`：代码工具加 `retrieve_docs`；
  - `full`：代码、RAG 和 Git 工具全部开放。
- 新增 `experiments.py`，支持 `Profile × Case × 重复次数` 的实验编排。
- `run_evals.py` 新增：
  - `--profile`：选择一个或多个 Profile；
  - `--compare`：比较全部三种 Profile；
  - `--runs`：每个组合重复 1 到 10 次。
- 新增 Profile 汇总、Profile + Case 稳定性汇总和全局汇总。
- 新增平均值、总体标准差、工具使用分布、强制总结率、格式兜底率和重复调用总数。
- `RunMetrics` 新增 `tool_profile` 和 `synthesis_used`。

### 安全与隔离

- 工具 Profile 使用两层权限控制：模型只看到白名单 Schema，执行节点再次校验白名单。
- `.incident_reports/` 被加入 Agent 内部目录，文件列表、读取和 Git Diff 都不能向模型泄露历史评测报告。

### 修正

- `connection_leak` 的根因关键词由实现手段 `finally` 改为根因事实 `泄漏`，减少正确答案被字面规则误判的情况。

### 验证

- 55 项离线测试通过。
- Profile Schema 过滤、执行层越权拒绝、重复实验、聚合统计、JSON 保存和评测隔离均有测试覆盖。
- 未自动运行真实多 Profile 实验，避免未经确认产生 API 费用。

---

## V5：确定性自动评测

### 新增

- 新增 `evaluation.py`，读取 `demo_app/evals/*.json` 并对 Agent 报告评分。
- 新增 `run_evals.py`，支持运行单个或全部案例并保存 JSON 报告。
- 新增 `run_agent_detailed()`，返回 `IncidentReport` 和 `RunMetrics`。
- 保留 `run_agent()` 的旧返回值，避免破坏命令行与已有调用方。
- 新增以下指标：
  - 根因关键词命中率；
  - 核心代码证据命中率；
  - 相关文档命中率；
  - 文件与行号引用有效率；
  - 模型和工具调用次数；
  - 唯一调用与重复调用次数；
  - 停止原因和运行耗时。

### 评分规则

- 根因关键词必须全部命中；
- 核心代码文件至少命中一半；
- 不能存在越界、不存在或行号无效的本地引用；
- 文档命中率和模型置信度作为观察指标，不作为硬通过条件。

### 验证

- V5 完成时共 47 项离线测试通过。
- 首次真实全工具评测结果为规则通过 2/3；人工检查发现 `connection_leak` 是关键词假阴性，三份报告的核心代码、文档和引用均达到 100%。

---

## V4.2：多行命令行输入

### 修复

- 旧版 `input()` 会把一次粘贴的多行 traceback 分成多个独立问题。
- 新增 `read_multiline_question()`：连续收集输入，以空行提交整段文本。
- `>` 表示第一行，`|` 表示同一问题的后续行。
- EOF 会提交已有内容或在无内容时退出；`Ctrl+C` 仍立即退出。

### 验证

- 增加多行合并、空输入、EOF 和只调用一次 Agent 的离线测试。

---

## V4.1：启动兼容、重复调用保护与强制总结

### 修复

- `demo_app/run_case.py` 支持模块启动和直接脚本启动，直接运行时自动补充项目根目录，避免 `No module named 'demo_app'`。
- 修复达到 `max_steps` 时最后一次工具请求未执行的问题。
- 新增工具调用签名，对工具名和规范化 JSON 参数完全相同的调用进行去重。
- 达到调查预算或发现重复调用时进入 `synthesize_report`，关闭工具并根据已有证据强制生成报告。
- 只有强制总结仍无法通过 Pydantic 验证时才生成确定性低置信度兜底报告。

### 验证

- 增加直接脚本启动、最后工具执行、参数规范化、重复拦截和强制总结测试。

---

## V4：本地 RAG、Git 工具与故障 Demo

### 新增

- 新增本地 Markdown RAG：标题感知切块、滑动窗口、特征哈希向量、余弦相似度和内容指纹缓存。
- RAG 数据源为 `knowledge/**/*.md` 和 `demo_app/docs/**/*.md`。
- 新增 `retrieve_docs` 工具，返回来源、章节、起始行、正文和相关度。
- 新增三个只读 Git 工具：`git_status`、`git_diff`、`git_log`。
- 新增 `demo_app/` 故障夹具：
  - 缺少 `user_id` 输入校验；
  - 数据库 `user_id → external_id` 迁移不一致；
  - 异常路径连接泄漏。
- 新增业务文档、日志、历史事故和三份标准答案。
- 最终证据来源扩展为 `code`、`documentation`、`git`、`runtime` 和 `unknown`。

### 安全

- RAG 完全本地运行，不下载 Embedding 模型，也不调用外部 Embedding API。
- Git 命令固定参数、只读、禁用 Shell，并限制超时与输出长度。
- `evals/`、缓存和敏感配置对 Agent 工具不可见。

---

## V3：迁移到 LangGraph

### 修改

- 将原生 Python 循环迁移为显式 `StateGraph`。
- 引入共享 `AgentState`、条件路由和节点级职责。
- 核心节点包括模型调用、工具执行、报告验证和兜底结束。
- `messages` 使用 reducer 追加消息，其他状态字段使用覆盖更新。
- SDK 消息转换为普通字典，方便 Checkpoint 序列化。
- 使用 `InMemorySaver` 和独立 thread ID 保存进程内状态快照。
- 区分业务调查预算 `max_steps` 与 LangGraph `recursion_limit`。

### 兼容

- 要求 Python 3.10+。
- LangGraph 依赖限制在 `>=1.0.0,<2.0.0`。

---

## V2：工具注册、结构化输出与供应商兼容

### 新增

- 新增统一 `ToolRegistry`，集中管理工具名、说明、参数模型和执行函数。
- 使用 Pydantic 严格校验工具参数，统一返回 `ToolResult`。
- 新增 `list_files`，用于在线索不足时查看有限深度项目结构。
- 最终输出改为 `IncidentReport`：摘要、根因、证据、修复建议和置信度。
- 新增 OpenAI 兼容配置层，只通过 `api.env` 切换 API Key、地址、模型和能力开关。
- 自动为 OpenAI 选择 `json_schema`，为 DeepSeek 和未知兼容服务选择更保守的 `json_object`。
- 支持手动设置 `OUTPUT_MODE` 和 `STRICT_TOOLS`。

### 修复

- 处理第三方兼容服务不支持 `response_format=json_schema` 导致的 HTTP 400。

---

## V1：最小 Agent Loop

### 新增

- 建立最小 Python Agent Loop。
- 支持 OpenAI 兼容 Chat Completions 和 Tool Calling。
- 首批工具为 `search_code` 与 `read_file`。
- Agent 根据用户 traceback 搜索项目、读取候选文件并循环收集证据。
- 第一阶段只诊断和提出建议，不自动运行或修改用户项目。
- 建立 `api.env.example`、依赖文件、基础测试和项目说明。
