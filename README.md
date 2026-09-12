# IncidentPilot V8.1.1

IncidentPilot 是一个面向 Python 项目的只读故障诊断 Agent。用户提交 traceback 或问题描述后，模型通过受控工具查看当前工作区的代码、文档和 Git 信息，循环收集证据，最后输出结构化根因报告。

当前版本的重点是：

- 使用 LangGraph 显式组织 Agent 控制流；
- 每次模型请求前压缩历史，只发送原始问题、当前假设和必要 Observation 摘要；
- 总结和格式修复时切换到证据保全模式，重新纳入所有带真实来源的成功 Observation；
- 每轮最多执行三个外部工具，阻止一次响应并发铺开大量低价值调查；
- 使用统一注册器管理七个只读工具；
- 使用内部 `update_hypotheses` 控制工具维护候选根因、支持证据和反证；
- 使用结构化 `next_action` 明确下一工具、目的、支持条件和否定条件；
- 新证据产生后强制先更新假设，未归类前禁止继续调用外部工具；
- 在 confirmed 假设获得两项独立 Observation 后提前总结；
- 使用 LangGraph 原生 interrupt 和 checkpoint 实现人工暂停与恢复；
- 同时限制调查轮数、模型调用数和工具调用数；
- 记录服务商返回的输入、输出和总 Token；
- 使用本地 RAG 检索项目文档；
- 使用只读 Git 工具调查变更；
- 使用 Pydantic 验证最终报告；
- 使用确定性 Evaluation 检查根因、证据和成本；
- 使用工具级与路径级双重隔离的三种 Tool Profile 做消融实验；
- 重复运行同一道题并统计稳定性；
- 保存结构化 Tool Observation 调查轨迹；
- 使用 Claim—Evidence Ledger 将结论绑定到实际工具结果；
- 验证代码行、RAG 片段和 Git 提交的真实来源；
- 统计上下文压缩、Observation 利用率和确认根因后的额外调用。
- 将每次报告验证错误持久化到 Evaluation JSON，保留字段路径和具体原因。

当前版本不会执行目标项目、修改代码或操作生产环境。模型能看到工具返回的代码和文档片段，因此使用第三方模型服务前，应确认项目内容允许发送给该服务商。

版本演进单独记录在 [CHANGELOG.md](CHANGELOG.md)。README 只描述当前 V8.1.1 的真实实现。

## 1. 快速开始

### 1.1 环境要求

- Windows PowerShell；
- Python 3.10 或更高版本；
- 一个支持 OpenAI 兼容 Chat Completions 和 Tool Calling 的模型服务；
- Git 仅在使用 Git 工具时需要。

项目依赖：

```text
openai>=1.0.0
python-dotenv>=1.0.0
pydantic>=2.0.0
langgraph>=1.0.0,<2.0.0
```

### 1.2 创建虚拟环境并安装依赖

在项目根目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

后续命令直接使用 `.venv\Scripts\python.exe`，不要求激活虚拟环境，也可以避免误用系统中的另一个 Python。

如果 PowerShell 在执行 `Activate.ps1` 时提示“在此系统上禁止运行脚本”，说明 Windows Execution Policy 阻止了激活脚本，并不表示虚拟环境损坏。推荐跳过激活，直接运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

注意路径开头是 `.\`，完整形式为 `.\.venv`，不是 `..venv`。如果确实希望激活，可以只为当前 PowerShell 窗口临时放行，再执行激活脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

`-Scope Process` 只影响当前 PowerShell 进程；关闭窗口后失效，不会永久修改系统策略。

### 1.3 配置模型 API

复制 `api.env.example` 为 `api.env`，然后填写：

```env
API_KEY=你的真实密钥
BASE_URL=服务商提供的OpenAI兼容地址
MODEL=服务商提供的模型ID
OUTPUT_MODE=auto
STRICT_TOOLS=auto
MAX_MODEL_CALLS=10
MAX_TOOL_CALLS=20
MAX_TOOLS_PER_STEP=3
HITL_MODEL_CALL_THRESHOLD=5
HITL_TOOL_CALL_THRESHOLD=10
```

字段含义：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `API_KEY` | 是 | 模型服务密钥 |
| `BASE_URL` | 否 | OpenAI 兼容 API 地址，默认是 OpenAI 官方地址 |
| `MODEL` | 是 | 模型 ID，必须支持 Tool Calling |
| `OUTPUT_MODE` | 否 | `auto`、`json_schema`、`json_object` 或 `text` |
| `STRICT_TOOLS` | 否 | `auto`、`true` 或 `false` |
| `MAX_MODEL_CALLS` | 否 | 一次运行的模型调用硬预算，默认 10，至少为 3 |
| `MAX_TOOL_CALLS` | 否 | 模型提出的工具调用硬预算，默认 20 |
| `MAX_TOOLS_PER_STEP` | 否 | 每个调查轮最多执行的外部工具数，默认 3，至少为 1 |
| `HITL_MODEL_CALL_THRESHOLD` | 否 | 交互模式达到多少次模型调用后请求人工确认，默认 5 |
| `HITL_TOOL_CALL_THRESHOLD` | 否 | 交互模式达到多少次工具调用后请求人工确认，默认 10 |

`OUTPUT_MODE=auto` 的当前策略：

- OpenAI 官方地址使用 `json_schema`；
- DeepSeek 和其他兼容服务使用更保守的 `json_object`。

`STRICT_TOOLS=auto` 的当前策略：

- OpenAI 官方地址启用严格工具 Schema；
- DeepSeek `/beta` 地址启用严格工具 Schema；
- 其他兼容服务默认关闭。

如果服务商返回：

```text
This response_format type is unavailable now
```

可以显式设置：

```env
OUTPUT_MODE=json_object
```

无论服务商是否支持原生 JSON Schema，最终文本都会经过本地 Pydantic 验证。

`api.env` 已被 `.gitignore` 排除。不要把真实密钥写入 `api.env.example`、README、评测报告或 Git 提交。

### 1.4 启动 Agent

```powershell
.venv\Scripts\python.exe main.py
```

命令行支持多行输入。粘贴完整 traceback 后，在新的 `|` 提示符处再按一次 Enter，用空行提交整段内容：

```text
> Traceback (most recent call last):
|   File "demo_app/run_case.py", line 24, in run_case
|     post_users({"email": "demo@example.com"}, create_connection())
|   File "demo_app/app/service.py", line 10, in create_user
|     user_id = payload["user_id"]
| KeyError: 'user_id'
|
```

`>` 和 `|` 是程序显示的提示符，不会发送给模型。单行问题也要再输入一个空行才会提交。输入 `exit` 或 `quit`，再输入空行，可以退出。

## 2. 当前能力与边界

### 2.1 能做什么

IncidentPilot 可以：

- 从 traceback 提取文件、行号、函数和异常类型；
- 在当前项目中搜索关键词；
- 读取带行号的 UTF-8 文本文件；
- 查看有限深度的项目目录；
- 检索本地 Markdown 知识库；
- 查看 Git 状态、未提交差异和最近提交；
- 多轮调用工具并保留观察结果；
- 显式维护可证伪候选假设、支持 Observation、反证和下一步动作；
- 将下一步动作约束为一个工具、调查目的、支持条件和否定条件；
- 每轮只执行有限数量的最高信息增益工具；
- 压缩发给模型的历史上下文，同时在 Checkpoint 保留完整调查轨迹；
- 新 Observation 未写入假设时阻止继续扩散调查；
- 在根因获得两项独立来源支持时提前停止扩散调查；
- 识别完全相同的重复工具调用；
- 在调查预算耗尽时根据已有证据强制总结；
- 在费用阈值、受保护路径或冲突假设处暂停，由用户选择继续、总结或取消；
- 使用 Checkpoint 从同一人工中断点恢复；
- 统计 Token、上下文压缩、Observation 利用率、早停、人工确认、格式修复和受保护路径尝试；
- 为每次工具调用保存参数、来源、摘要哈希和耗时；
- 输出根因、Claim—Evidence Ledger、修复建议和置信度；
- 拒绝未读取文件、越界行号、伪造 Observation 和虚假 Git 提交；
- 接受纯 JSON、JSON 代码块和前后带少量说明的合法报告，并记录历次验证错误；
- 批量评测六个故障诊断案例；
- 比较不同工具组合并统计多次运行稳定性。

### 2.2 不能做什么

当前版本不会：

- 执行 Agent 自己提出的任意命令；
- 自动运行用户项目复现故障；
- 修改、删除或创建业务代码；
- 自动应用修复补丁；
- 自动运行修复后的测试；
- 连接生产数据库或生产环境；
- 跨进程持久化 LangGraph Checkpoint；
- 对任意外部项目动态切换调查根目录。

文件工具的根目录固定为 IncidentPilot 当前仓库。因此现阶段主要用于调查本仓库中的 `demo_app` 和项目自身代码。支持任意目标仓库需要后续增加经过验证的 workspace 参数和更严格的隔离。

## 3. 项目结构

```text
incident-pilot/
├── api.env.example             # API 配置模板
├── requirements.txt            # Python 依赖
├── main.py                     # 多行命令行入口与报告展示
├── agent.py                    # Agent 公共接口、图调用与运行指标
├── graph.py                    # LangGraph 状态、节点、路由和收尾逻辑
├── context_manager.py          # 发给模型的调查上下文选择与压缩
├── models.py                   # Pydantic 工具、报告和指标模型
├── hypotheses.py              # 假设控制工具、引用校验和证据充分度 Gate
├── provenance.py               # Observation 提取与证据来源验证
├── config.py                   # api.env 加载与供应商能力适配
├── registry.py                 # 工具注册、Schema、参数校验与执行
├── tools.py                    # 文件读取、代码搜索和目录列表
├── knowledge_tools.py          # retrieve_docs 工具
├── retrieval.py               # 本地 Markdown RAG
├── git_tools.py               # 三个只读 Git 工具
├── tool_profiles.py            # Profile 工具白名单与文档路径隔离
├── evaluation.py              # 单案例确定性评分
├── experiments.py             # Profile、Case、重复运行与统计聚合
├── run_evals.py               # 真实模型评测命令行
├── knowledge/
│   ├── api.md                  # 模型输出兼容知识
│   ├── database.md             # 当前状态存储知识
│   └── troubleshooting.md      # 项目排障手册
├── demo_app/
│   ├── app/                    # 故意包含多个 Bug 的模拟业务代码
│   ├── docs/                   # RAG 专用的规范、Runbook 和事故文档
│   ├── fixtures/               # Agent 不可见的外部系统模拟器
│   ├── logs/                   # 可用于提问的简化 traceback
│   ├── evals/                  # Agent 不可见的标准答案
│   └── run_case.py             # 四个可执行故障的入口
├── test_agent.py
├── test_context_manager.py
├── test_demo_app.py
├── test_evaluation.py
├── test_experiments.py
├── test_graph.py
├── test_hypotheses.py
├── test_main.py
├── test_provenance.py
├── test_tools.py
├── README.md                   # 当前版本完整说明
└── CHANGELOG.md                # 版本演进记录
```

运行时还可能生成：

```text
.incident_cache/rag_index.json  # RAG 索引缓存
.incident_reports/*.json        # Evaluation 与实验报告
```

两个目录都被 Git 忽略，也不会暴露给 Agent 工具。

## 4. 从输入到报告的完整数据流

```text
main.py 收集一段完整多行输入
        ↓
run_agent(question)
        ↓
agent.py 加载 api.env、解析 Tool Profile、创建模型客户端
        ↓
构建 LangGraph 并创建初始 AgentState
        ↓
call_model
        ├── context_manager 生成最小请求上下文
        │       ├── 保留原始 System 与 User 问题
        │       ├── 保留全部假设引用的 Observation
        │       └── 仅补充最近 4 条尚未引用的 Observation
        ├── update_hypotheses → 校验并替换当前完整假设集合
        ├── 外部 tool_calls → execute_tools
        │                       ├── 执行只读工具并生成 obs-xxx
        │                       ├── 提取文件、行号、Chunk 或 Commit
        │                       ├── 更新假设支持与反证
        │                       └── 检查证据充分度、硬预算和 HITL 条件
        │                                  ├── confirmed + 两项独立来源 → 提前总结
        │                                  ├── 费用阈值/冲突/保护路径 → human_review
        │                                  │                              ├── continue → 继续
        │                                  │                              ├── summarize → 总结
        │                                  │                              └── cancel → 取消
        │                                  ├── 硬预算耗尽 → 强制总结
        │                                  └── 仍需调查 → call_model
        │
        └── 返回报告文本 → Pydantic + Provenance 验证
                                ├── Schema、Claim 和来源全部合法 → END
                                ├── 伪造来源或越界 → 带错误重试
                                ├── 可重试 → call_model
                                └── 强制总结非法 → repair_report
                                                        ├── 合法 → END
                                                        └── 仍非法 → build_fallback → END
        ↓
IncidentReport
        ↓
main.py 格式化为人类可读文本
```

模型本身不能直接读取磁盘。模型只能选择注册过的工具，真正的文件、RAG 和 Git 操作由本地 Python 函数执行。工具结果先进入完整 LangGraph 状态并生成系统控制的 Observation；下一次请求不再重发整段 Assistant/Tool 消息，而是发送压缩调查记忆。这样避免悬空的 `tool_call_id`，也避免早期大段工具输出在之后每一轮重复计费。普通调查保留假设引用和最近结果；最终总结、修复则保留所有具有真实来源的成功结果。完整消息、Observation 和假设仍在 Checkpoint 中，可用于验证和审计。

## 5. LangGraph 控制流

### 5.1 AgentState

图中的共享状态包含：

| 字段 | 作用 |
|---|---|
| `messages` | System、User、Assistant 与 Tool 消息历史 |
| `step_count` | 调查阶段的模型请求次数 |
| `tool_call_count` | 模型提出的工具调用总数 |
| `max_steps` | 调查阶段模型请求预算，默认 8 |
| `model_call_count / max_model_calls` | 包括总结和修复在内的模型调用与硬预算 |
| `tool_call_count / max_tool_calls` | 内部控制调用与外部工具请求总量及硬预算 |
| `max_tools_per_step` | 一轮模型响应最多允许执行的外部工具数，默认 3 |
| `input/output/total_token_count` | 服务商返回的 Token 使用量；不可用时为 0 |
| `report` | 通过验证的最终报告 |
| `validation_error` | 最近一次报告格式错误 |
| `stop_reason` | `completed` 或 `invalid_synthesis` 等结束原因 |
| `tool_call_signatures` | 已实际执行的唯一工具名和规范化参数 |
| `repeated_tool_call_count` | 被拦截的完全重复调用数 |
| `force_synthesis` | 是否应该停止调查并强制总结 |
| `synthesis_attempted` | 是否已经进行过无工具总结 |
| `repair_attempted` | 是否已经进行过最后一次无工具格式修复 |
| `observations` | 系统生成的结构化工具调用轨迹，只追加不覆盖 |
| `hypotheses` | 当前完整候选根因集合，包含状态、支持 Observation 和反证 |
| `context_compaction_count` | 实际使用压缩请求上下文的模型调用次数 |
| `confirmed_at_tool_call_count` | 首次形成 confirmed 假设时的工具调用计数，用于测量确认后的浪费 |
| `hypothesis_update_required` | 新成功 Observation 是否仍待写入假设；为真时外部工具暂时关闭 |
| `validation_errors` | 历次报告格式、假设准备度和 Provenance 验证错误，只追加不覆盖 |
| `evidence_sufficient / early_stopped` | 是否满足确定性证据充分度并提前收尾 |
| `human_review_*` | 是否启用 HITL、触发原因、次数和是否已经处理 |
| `cancelled` | 用户是否在人工决策点取消调查 |

`messages` 使用追加 reducer。节点只返回新增消息，LangGraph 将其追加到完整历史；计数、报告和布尔值等字段由节点返回的新值覆盖。V8.1.1 的压缩与证据保全发生在模型请求边界，不会修改这个完整状态。

每次 `run_agent()` 默认生成新的 UUID 作为 thread ID，避免不同问题共享状态。当前 Checkpointer 是 `InMemorySaver`，人工暂停与 `Command(resume=...)` 能在同一 Python 进程内恢复；关闭进程后状态仍会消失。

### 5.2 节点

#### `call_model`

先通过 `context_manager.py` 生成压缩请求，再把当前 Profile 的外部工具、内部 `update_hypotheses` Schema 和输出格式发送给模型。普通压缩记忆包含完整假设、假设所引用的全部 Observation，以及最近 4 条尚未归类的 Observation；每条结果摘要最多 700 字符，但保留 ID、参数、成功状态和精确来源。若上一轮产生了新成功证据，请求中会追加醒目的控制门提示，模型必须先更新假设。模型先提出 2–4 个可证伪候选根因，再用最有区分度的工具验证；也可以在证据足够时直接生成最终 JSON。

未确认或仅 supported 的假设必须提供结构化 `next_action`：`tool_name` 表示下一项工具，`purpose` 解释信息价值，`supports_if` 和 `rejects_if` 预先声明什么结果会支持或否定它。这迫使调查先说明“为什么查”，而不是漫无目的地遍历文件。

#### `execute_tools`

外部工具按名称进入注册器，使用 Pydantic 校验参数并执行。每个外部调用生成唯一 `obs-xxx`，记录参数、状态、来源、摘要哈希和耗时。内部 `update_hypotheses` 不访问工作区，也不生成可用于 Evidence 的 Observation；它只能引用已经存在且成功的 Observation，并用完整集合替换图中的假设状态。已有假设时，只要一轮生成新成功 Observation，`hypothesis_update_required` 就会开启；下一轮在假设更新成功前提出的外部调用会收到 `hypothesis_update_required`，不会实际执行。

工具硬预算在执行层再次检查。超过 `MAX_TOOL_CALLS` 的请求不会执行，并收到 `tool_budget_exhausted`，随后图进入总结，不能靠一次并行请求绕过预算。同一轮超过 `MAX_TOOLS_PER_STEP` 的调用收到 `per_step_tool_limit`，但不会立刻强制总结；模型下一轮可以根据已有结果重新排序，只选择信息价值最高的动作。

#### `human_review`

交互式 `main.py` 会在以下情况使用 LangGraph `interrupt()` 暂停：达到模型或工具费用阈值、尝试受保护路径、出现多个高置信度 confirmed 假设。状态由 Checkpointer 保存，用户可以选择继续调查、使用已有证据总结或取消；`agent.py` 使用 `Command(resume=...)` 从同一个节点恢复。Evaluation 默认关闭 HITL，避免批处理等待输入。

#### 证据充分度 Gate

只有状态为 `confirmed`、置信度至少 0.8、没有反证，并绑定至少两个成功 Observation 的假设才可能提前停止；两项 Observation 还必须来自不同来源类型，或至少两个不同文件。单条线索和模型自报 high confidence 都不足以触发早停。

#### `validate_report`

先使用 `IncidentReport.model_validate_json()` 验证模型输出，再检查 Claim 引用、Observation 是否存在、工具是否成功、来源类型、文件、行号范围和 Git 提交。任何一项不匹配都会把具体错误加入消息，让模型根据真实 Observation 修正，而不是接受“文件确实存在但模型没有读过”的引用。

#### `synthesize_report`

证据充分、达到调查/模型/工具硬预算，或第二次发现完全重复调用后，不再向模型提供工具，只要求它使用现有 Observation 和假设生成报告。此时上下文切换为证据保全模式：纳入全部具有真实来源的成功 Observation、全部假设引用和最近两条失败结果，避免关键但尚未绑定的旧证据被普通窗口淘汰。这次请求不计入调查 `step_count`，但计入总模型调用与 Token。

#### `repair_report`

如果无工具强制总结仍未通过 Pydantic 或 Provenance 验证，系统会再提供一次不带工具的严格 JSON 格式修复机会。修复请求包含具体字段路径、错误原因、上一次报告和完整证据候选，并明确要求在缺少 confirmed 假设时降低置信度。它不允许重新调查，避免已经取得的 Git 或代码证据因为一次格式错误全部丢失。

#### `build_fallback`

如果最后一次格式修复仍不符合要求，系统优先从最高置信度的 supported/confirmed 假设及其真实支持 Observation 构造有来源的降级报告；没有可用假设时才返回通用低置信度说明。结束原因仍为 `invalid_synthesis`，Evaluation 不会把降级结果伪装成正常通过。

#### `build_cancelled`

用户在 HITL 节点选择取消时，不再请求模型，直接生成低置信度取消报告，并以 `stop_reason=cancelled` 结束。

### 5.3 多层成本与循环保护

第一层是业务预算：

```python
max_steps = 8
```

它控制允许使用工具的调查轮数。除此以外，V8.1.1 还分别限制总模型调用、总工具调用和单轮工具调用；模型硬预算会预留一次总结和一次格式修复机会。每次请求再通过确定性上下文选择器控制重复输入量。最后由 LangGraph `recursion_limit` 限制节点跳转总数。这些计数对象不同，不能互相替代。

LangGraph 框架保险为：

```python
recursion_limit = max_steps * 3 + 5
```

它限制节点跳转总数，防止图结构异常循环。两者统计对象不同，不能互相替代。

### 5.4 重复调用保护

工具签名采用：

```text
工具名 + 规范化后的 JSON 参数
```

JSON 参数会按键名排序，因此以下调用被视为相同：

```json
{"query":"user_id","path":"."}
{"path":".","query":"user_id"}
```

完全相同的调用不会再次执行，而是返回 `duplicate_tool_call`。第一次重复后，模型还有一轮机会使用已有结果、改查其他证据或直接输出报告；同一次调查中第二次重复才触发强制总结。语义相似但参数不同的调用目前不会被识别，例如搜索 `user_id` 和搜索 `missing user_id` 仍被视为两次不同调查。

## 6. 工具注册与七个只读工具

### 6.1 ToolRegistry

每个工具注册时提供：

- 工具名；
- 用途说明；
- Pydantic 参数模型；
- 实际 Python 函数。

注册器负责：

1. 防止工具重名；
2. 生成发给模型的 Function Calling Schema；
3. 按 Profile 筛选可见 Schema；
4. 严格校验模型参数；
5. 拒绝当前 Profile 不允许的调用；
6. 将成功和错误统一转换成 `ToolResult` JSON。

统一结果格式：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {}
}
```

工具失败也作为 Observation 返回给模型，而不是直接让整个 Agent 崩溃。

### 6.2 文件工具

| 工具 | 参数 | 行为与限制 |
|---|---|---|
| `read_file` | `path` | 读取项目内 UTF-8 文件，返回带行号内容，最多 20,000 字符 |
| `search_code` | `query` | 在允许的文本后缀中大小写不敏感搜索，最多 50 条匹配 |
| `list_files` | `path`、`max_depth` | 列出目录和文件，深度 1–5，最多 200 项 |

底层搜索后缀包括 Python、Markdown、文本、JSON、TOML、YAML；但正常 Agent 运行总会激活 Profile，因此 Markdown 会被路径策略过滤，只能经 RAG 获取。文件路径在解析后必须仍位于项目根目录内。

### 6.3 RAG 工具

`retrieve_docs(query, top_k)` 在本地知识库中返回最多 1–5 个相关片段。返回字段包括：

```text
chunk_id
source
section
line_start
line_end
content
score
```

### 6.4 Git 工具

| 工具 | 行为 |
|---|---|
| `git_status()` | 查看当前分支和工作区改动 |
| `git_diff(path)` | 查看一个指定现有非文档文件的未提交差异；拒绝目录和点号 |
| `git_log(limit)` | 查看最近 1–20 条提交的哈希、作者、时间和标题 |

Git 工具只使用预先定义的参数列表，`shell=False`，超时 8 秒，输出最多 20,000 字符。它们不会执行提交、重置、切换分支或修改工作区。

## 7. 本地 RAG 原理

### 7.1 数据源

RAG 只索引：

```text
knowledge/**/*.md
demo_app/docs/**/*.md
```

它不索引源代码、日志、`evals/`、`api.env` 或历史评测报告。源代码由文件工具调查；标准答案必须与 Agent 隔离。

### 7.2 切块

Markdown 首先按 `#` 到 `######` 标题切成章节。超过 900 字符的章节再使用滑动窗口切分，窗口重叠 120 字符，降低跨边界信息丢失。

每个 Chunk 保存来源文件、标题、起始行、正文和稳定 ID。

### 7.3 向量与检索

当前 RAG 不使用外部 Embedding API，也不下载大型模型。它提取：

- 英文单词和代码标识符；
- 中文单字；
- 中文双字组合。

每个 Token 通过 BLAKE2b 稳定哈希映射到 512 维向量，并进行归一化。查询与 Chunk 使用余弦相似度排序，只返回正相关且分数最高的 `top_k` 项。

这是一种轻量、免费、可离线复现的检索方法，适合当前小型知识库，但语义能力弱于真正的 Embedding 模型。

### 7.4 缓存失效

所有知识文件的相对路径和内容共同生成 SHA-256 指纹。缓存指纹一致时复用 `.incident_cache/rag_index.json`；文档新增、删除或内容变化后，指纹变化并自动重建索引。

## 8. Hypothesis- and Evidence-Driven Diagnosis

### 8.1 Diagnostic Hypothesis

模型通过内部控制工具维护以下结构：

```text
DiagnosticHypothesis
├── hypothesis_id
├── statement
├── status                    # unverified / supported / rejected / confirmed
├── confidence                # 0.0–1.0
├── supporting_observation_ids[]
├── contradicting_observation_ids[]
└── next_action
```

`supported` 和 `confirmed` 必须至少引用一条成功 Observation，`rejected` 必须引用反证；不存在或失败的 Observation 不能改变假设状态。模型每次提交的是当前完整集合，这使状态可 checkpoint、可评测，也避免只从自然语言 Thought 猜测 Agent 当前相信什么。

最终报告还有状态门槛：`high` 必须至少存在一个 `confirmed` 假设，`medium` 必须至少存在一个 `supported` 或 `confirmed` 假设；只有 `low` 可以在没有已支持假设时诚实结束。假设状态不替代 V7 的 Claim—Evidence Provenance，二者会分别验证。

### 8.2 Tool Observation

每次工具调用都会生成由系统控制的 `ToolObservation`：

```text
ToolObservation
├── observation_id       # obs-001
├── tool_call_id         # 模型调用 ID
├── step                 # 调查轮次
├── tool_name
├── arguments            # 已解析参数
├── ok / repeated
├── sources[]            # 实际观察到的文件、行、Chunk 或 Commit
├── error
├── result_sha256        # 带 Observation ID 的结果摘要哈希
├── result_excerpt       # 最多 1000 字符，便于审计
└── duration_ms
```

`read_file` 生成文件行号范围，`search_code` 生成每个命中行，`retrieve_docs` 生成文档 Chunk 和起止行，`git_log` 生成 Commit，`git_diff` 生成文件与 Diff Hunk。失败或重复调用也有 Observation，但 `ok=false`，不能作为支持性证据。

### 8.3 Claim—Evidence Ledger

最终报告结构为：

```text
IncidentReport
├── summary
├── root_cause
├── claims[]
│   ├── claim_id
│   ├── statement
│   └── evidence_ids[]
├── evidence[]
│   ├── evidence_id
│   ├── observation_id
│   ├── source_type
│   ├── file
│   ├── line_start / line_end
│   ├── commit_hash
│   └── description
├── suggested_fixes[]
└── confidence
```

代码、文档和运行日志证据必须填写真实文件与已观察行号。Git Commit 证据使用 `commit_hash`，文件留空、行号填 `null`。每条 Claim 必须引用存在的 Evidence；`medium` 或 `high` 报告必须至少包含一个有证据的 Claim。

### 8.4 确定性来源验证

`provenance.py` 在接受报告前检查：

1. Claim ID 和 Evidence ID 唯一；
2. Claim 引用的 Evidence 全部存在；
3. Evidence 引用的 Observation 真实存在且工具执行成功；
4. `source_type` 与工具结果一致；
5. 文件和行号落在该 Observation 的真实返回范围；
6. Git 短哈希能够匹配 `git_log` 返回的完整 Commit；
7. 不允许存在未被任何 Claim 使用的游离 Evidence。

这能证明“模型确实观察过所引用的位置”，但还不能仅靠确定性代码判断一段证据在语义上是否充分支持自然语言 Claim。语义支持、反证和置信度校准仍属于后续混合评测范围。

## 9. Demo App：确定性故障夹具

`demo_app` 是供 IncidentPilot 调查的模拟业务系统，不是生产应用。Bug 被故意保留，目的是生成稳定、真实、可评分的故障。故障源码不使用直接写明答案的 `BUG-xxx` 注释，以降低答案泄漏。

### 9.1 缺少输入校验

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
```

预期：

```text
KeyError: 'user_id'
```

调用链为 `run_case → post_users → create_user → payload["user_id"]`。API 层没有校验必填字段，Service 直接使用字典下标。

### 9.2 数据库迁移不一致

```powershell
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
```

预期：

```text
sqlite3.OperationalError: table users has no column named user_id
```

数据库已经使用 `external_id`，Repository 的 INSERT 仍写入旧字段 `user_id`。

### 9.3 异常路径连接泄漏

```powershell
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
```

预期：

```text
RuntimeError: connection pool exhausted
```

Worker 获取连接后在无效任务分支抛出异常，没有执行 `release`。连续失败后活动连接达到上限。

### 9.4 供应商文档约束

```powershell
.venv\Scripts\python.exe -m demo_app.run_case documentation_required
```

预期：

```text
RuntimeError: HTTP 422: timeout_policy_violation
```

应用把 `WEBHOOK_TIMEOUT_SECONDS` 配置为 30，但外部供应商 Acme Notify v2 的契约规定 `timeout_seconds` 最大为 10。供应商限制位于 Agent 不可见的运行夹具中；Agent 必须通过 RAG 查询 `demo_app/docs/integrations.md` 才能获得准确上限。

以上四个命令应该以非零状态退出。这里“测试成功”的含义是故障按预期稳定复现，而不是业务代码正确。

也支持直接脚本启动：

```powershell
.venv\Scripts\python.exe demo_app\run_case.py missing_user_id
```

入口会在直接脚本模式下补充项目根目录，避免 `No module named 'demo_app'`。模块方式仍然是推荐用法。

## 10. 确定性 Evaluation

### 10.1 标准答案

`demo_app/evals/*.json` 包含：

```text
case_id
question
expected_exception
root_cause_keywords
evidence_files
relevant_docs
```

只有 `question` 发送给 Agent，其他字段由评测器保存并用于评分。`evals/`、评测实现和对应测试均对 Agent 隔离；`git_diff` 必须指定单个现有代码文件，不能再用点号读取整个工作区并绕过隔离。

### 10.2 单案例评分

评测器计算：

- 异常类型是否在报告出现；
- 根因关键词命中率；
- 标准代码文件命中率；
- 相关文档命中率；
- 引用文件与行号有效率；
- Evidence Observation 落地率；
- Claim 证据覆盖率；
- Provenance 违规数量。

当前硬通过条件是：

```text
根因关键词命中率 = 100%
并且核心代码文件命中率 >= 50%
并且无效本地引用数 = 0
并且 Evidence Observation 落地率 = 100%
并且 Claim 证据覆盖率 = 100%
并且 Provenance 违规数 = 0
并且 stop_reason = completed
```

根因关键词在 `summary + root_cause + claims[].statement` 中匹配。V8 延续 Claim 作为经过 Evidence 绑定的正式诊断结论，因此其中的精确配置值计入根因评分；修复建议和证据描述仍不参与，避免模型在非结论区域堆关键词。文档命中、异常类型和模型置信度是观察指标，不是硬门槛。

相关文档只有在对应 Evidence 绑定到真实 `retrieve_docs` Observation，并且该 Observation 确实返回了目标文档片段时才计分。仅调用一次 RAG 或猜中文档路径都不算命中。数值型根因标准使用带单位的短语，例如 `10 秒`，避免代码中的“第 10 行”被误判为正确阈值。

引用验证同时检查本地物理位置和本次工具 Observation：文件不仅要存在，模型还必须真正读取过对应行；Git 提交则必须真实出现在绑定的 `git_log` 结果中。

### 10.3 运行指标

`run_agent_detailed()` 返回：

```text
AgentRunResult
├── report: IncidentReport
├── metrics: RunMetrics
├── observations[]: ToolObservation
├── hypotheses[]: DiagnosticHypothesis
└── validation_errors[]: 历次报告验证错误
```

`RunMetrics` 包含：

| 字段 | 含义 |
|---|---|
| `tool_profile` | 本次工具组合 |
| `model_call_count` | 包括强制总结和格式修复在内的模型请求总数 |
| `investigation_step_count` | 可以使用工具的调查模型轮数 |
| `tool_call_count` | 模型提出的工具调用总数 |
| `unique_tool_call_count` | 实际执行的唯一外部工具调用数；不包含内部假设状态更新 |
| `repeated_tool_call_count` | 被去重保护拦截的数量 |
| `observation_count` | 成功、失败和重复调用生成的 Observation 总数 |
| `successful_observation_count` | 成功执行且非重复的 Observation 数量 |
| `synthesis_used` | 是否使用强制总结 |
| `format_repair_used` | 是否进行过最后一次无工具格式修复 |
| `early_stopped` | 是否在调查轮数、模型和工具硬预算之前，因 confirmed 假设证据充分而提前总结 |
| `hypothesis_count / confirmed_hypothesis_count` | 最终假设总数和已确认数量 |
| `human_review_count` | LangGraph HITL 人工决策次数 |
| `protected_access_attempt_count` | 被安全边界拦截的保护路径访问次数 |
| `input/output/total_token_count` | 服务商返回的 Token；服务商不提供时为 0 |
| `context_compaction_count` | 使用压缩调查记忆请求模型的次数 |
| `unreferenced_successful_observation_count` | 运行结束时既未被假设也未被最终报告使用的成功 Observation 数 |
| `observation_utilization_rate` | 被假设或最终 Evidence 使用的成功 Observation 比例；无成功 Observation 时为 1 |
| `post_confirmation_tool_call_count` | 首次形成 confirmed 假设后仍提出的工具调用数 |
| `tool_names` | 按请求顺序记录的工具名 |
| `stop_reason` | 图结束原因 |
| `duration_ms` | `app.invoke()` 的墙钟耗时 |

普通 `run_agent()` 仍然只返回 `IncidentReport`，保持现有调用方兼容。

## 11. V8.1.1 工具消融、上下文效率、成本与稳定性实验

### 11.1 三种 Profile

| Profile | 可用工具 | 实验目的 |
|---|---|---|
| `code_only` | 三个文件工具；不能直接看到 RAG 文档 | 验证只看代码和日志是否足够 |
| `code_rag` | 文件工具 + RAG；文档只能经 RAG 获取 | 测量项目文档的贡献 |
| `full` | 文件工具 + RAG + Git；文档只能经 RAG 获取 | 测量 Git 上下文的额外贡献 |

Profile 使用三层限制：模型只收到允许的工具 Schema，执行节点拒绝白名单外调用，文件工具再实施路径级隔离。启用任一 Profile 后，所有 Markdown 都不会出现在 `list_files` 和 `search_code` 结果中，`read_file` 也会拒绝直接读取；`code_rag` 和 `full` 必须调用 `retrieve_docs` 获取已建立索引的 `knowledge/` 与 `demo_app/docs/` 文档。`demo_app/fixtures/` 对所有 Agent Profile 都不可见。普通命令行默认使用 `full`。

### 11.2 六个案例的分工

| Case | 主要目的 |
|---|---|
| `missing_user_id` | 基础 API 调用链诊断 |
| `schema_mismatch` | 基础数据库字段不一致诊断 |
| `connection_leak` | 基础异常路径资源泄漏诊断 |
| `documentation_required` | 没有供应商文档就无法知道准确的 10 秒约束 |
| `git_regression` | 要求通过 Git 历史给出引入缺陷的提交 `61932b9` |
| `misleading_documentation` | 检查 Agent 能否识别已废弃的扩容建议并坚持代码证据 |

后三个是专门拉开工具能力差异的案例。`git_regression` 依赖本仓库现有 Git 历史；如果导出项目时丢失 `.git`，该案例中的 Git 组也无法取得标准提交哈希。

### 11.3 运行实验

默认组合仍是全部六个 Case、`full` Profile、每个一次，但 V8.1.1 的费用保护会在真正调用模型前阻止超过 3 次且没有显式确认的实验：

```powershell
.\.venv\Scripts\python.exe run_evals.py
```

上面的命令会显示 6 次调查并安全退出。日常请用 `--case` 缩小范围；只有确认费用后才追加 `--yes`。

最低成本的三组烟雾对照：

```powershell
.\.venv\Scripts\python.exe run_evals.py --case missing_user_id --compare
```

指定一个 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py --profile code_only
```

选择两个 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py `
  --profile code_only `
  --profile code_rag
```

比较全部 Profile：

```powershell
.venv\Scripts\python.exe run_evals.py --compare
```

每个组合重复三次：

```powershell
.\.venv\Scripts\python.exe run_evals.py --compare --runs 3 --yes
```

三种 Profile × 六个 Case × 三次等于 54 次 Agent 调查；每次调查内部又可能请求模型多次。建议先运行三次烟雾对照，再选择三个区分度案例做九次对照，最后根据费用决定是否运行全部 54 次稳定性实验。

推荐的 V8.1.1 区分度对照有 9 次，必须显式确认：

```powershell
.venv\Scripts\python.exe run_evals.py `
  --case documentation_required `
  --case git_regression `
  --case misleading_documentation `
  --compare `
  --yes
```

其他参数：

```text
--case CASE_ID       只运行指定案例，可重复
--max-steps N        每次调查的模型轮数预算
--profile PROFILE    选择 Profile，可重复
--compare            使用全部三种 Profile
--runs N             每个组合重复 1–10 次
--output PATH        自定义 JSON 输出路径
--yes                显式确认超过 3 次真实 Agent 调查
```

`--compare` 和 `--profile` 互斥。开始前程序会打印即将进行的 Agent 调查总数。

### 11.4 输出层级

JSON 报告默认保存到：

```text
.incident_reports/eval-YYYYMMDD-HHMMSS.json
```

结构为：

```text
ExperimentRun
├── profiles
├── runs_per_case
├── attempts             # 每次独立报告、指标、Observation 轨迹和得分
├── case_summaries       # Profile + Case 的重复运行稳定性
├── profile_summaries    # 每个 Profile 的综合表现
└── overall_summary      # 整次实验汇总
```

终端逐次结果额外显示“落地、Claim、违规、假设、早停、利用、压缩、Token”。“利用”是成功 Observation 最终进入假设或报告证据的比例，“压缩”是本次运行采用最小上下文的模型请求次数。失败案例随后显示机器可读原因，例如缺失根因关键词、未落地证据、无证据 Claim、Provenance 违规或异常停止原因。之后显示 Profile 对照；当 `runs > 1` 时还显示按案例稳定性。

每个 `attempts[]` 都持久化本次完整 `observations[]`、`hypotheses[]` 和 `validation_errors[]`。因此实验结束后既能复核 Evidence 引用的 Observation、工具参数、真实来源范围和执行状态，也能看到每一次报告为何被 Pydantic、假设准备度或 Provenance Validator 拒绝。

### 11.5 聚合指标

每个 Profile 汇总：

- 运行数、通过数、通过率；
- 根因、代码、文档、引用、Evidence 落地率和 Claim 覆盖率的平均值与总体标准差；
- Provenance 违规总数；
- 模型调用和工具调用的平均值与总体标准差；
- 重复工具调用总数；
- confirmed 假设平均数、证据充分早停次数与比例；
- 上下文压缩平均次数、Observation 利用率平均值与总体标准差；
- 未引用成功 Observation 总数、确认根因后的额外工具调用总数；
- 人工确认和受保护路径尝试次数；
- Token 平均值与标准差；
- 强制总结次数和比例；
- 格式修复次数、最终兜底次数和比例；
- 工具使用次数分布；
- 总耗时。

总体 Profile 标准差会同时受到案例难度和模型随机性影响。`case_summaries` 固定 Profile 和 Case，只比较同一道题的多次运行，更适合判断稳定性。一次运行的标准差为 0 仅表示没有足够样本，不能证明绝对稳定。

## 12. 测试

运行全部离线测试：

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

当前共有 94 项测试，覆盖：

- 模型服务能力配置；
- 工具注册、严格参数和统一错误；
- 路径越界、敏感配置和内部目录隔离；
- 文件、RAG 和 Git 工具；
- LangGraph 路由、报告重试、预算和强制总结；
- 内部假设工具的格式、ID、成功 Observation 与状态约束；
- 两项独立来源早停和单条证据不早停；
- 开放假设必须提供结构化下一步调查动作；
- 上下文压缩保留假设引用证据和最近未分类证据，并移除悬空 Tool 消息；
- 最终总结上下文保留所有具有来源的成功 Observation；
- 新证据未更新假设时阻止后续外部工具，更新完成后恢复调查；
- JSON 代码块及前后说明文字解析、详细验证错误持久化；
- 最终格式修复失败时，从真实 Observation 构造有来源的降级报告；
- 空 Evidence 报告的引用有效率记为 0%，不再显示误导性的 100%；
- 单轮工具上限拦截并行铺开，但允许下一轮重新规划；
- 直到最后预算轮才确认的假设不会被误记为早停；
- LangGraph 原生 HITL interrupt、checkpoint 与 resume；
- 超过三次真实调查的费用保护；
- 并行工具请求不能越过执行层硬预算，超额请求仍保留失败 Observation；
- 重复工具调用纠正窗口与二次重复保护；
- 强制总结失败后的单次无工具格式修复；
- Tool Profile Schema 过滤和执行层越权拒绝；
- 多行命令行输入；
- 四个可执行 Demo 故障稳定复现；
- Profile 对 RAG 文档和外部系统夹具的路径级隔离；
- 文档得分必须由 `retrieve_docs` 调用触发；
- 评分、引用验证和 JSON 保存；
- 带单位数值关键词和终端失败原因；
- Tool Observation 生成、ID 回传和来源范围提取；
- 伪造 Observation、越界行号和缺失 Evidence 拒绝；
- Git Commit 短哈希与真实 `git_log` Observation 绑定；
- Claim—Evidence Ledger 完整性与 Evidence 落地评分；
- 多 Profile、多次运行、标准差和聚合输出；
- 旧 `run_agent()` 接口兼容。

离线测试使用模拟模型，不读取真实 API Key，不产生模型费用。真实 Evaluation 与消融实验只有在主动运行 `run_evals.py` 时才调用 `api.env` 配置的模型。

## 13. 安全设计

### 13.1 路径和敏感文件

- 所有文件路径解析后必须仍在项目根目录；
- `api.env`、`.env` 等敏感配置不可读取或搜索；
- `.git`、`.venv`、缓存、构建目录和依赖目录不会进入文件列表或代码搜索；
- `evals/`、评测实现、评测测试、`.incident_cache/` 和 `.incident_reports/` 对 Agent 不可见；
- `git_diff` 只接受单个现有文件，不能用仓库根目录批量泄露隐藏内容；
- 二进制或非 UTF-8 文件不会作为文本发送给模型；
- 文件内容、搜索命中和目录项都有数量或长度限制。

### 13.2 只读边界

当前所有 Agent 工具都是只读的。Git 工具不通过 Shell 拼接命令，文件工具不提供写入，系统提示也明确禁止修改。Evaluation 自己会在 `.incident_reports/` 写报告，RAG 会在 `.incident_cache/` 写缓存；这两个写入属于本地基础设施，不是模型可调用的业务写入工具。

### 13.3 外部模型数据边界

文件和文档首先由本地工具读取，但工具结果会加入消息并发送给配置的模型服务。所谓“本地工具”不代表代码内容永远留在本机。不要用当前版本调查不允许发送给服务商的私有代码。

## 14. 如何提出高质量问题

最好提供：

1. 完整 traceback；
2. 实际运行命令；
3. 当前工作目录；
4. 预期行为；
5. 实际行为；
6. 最近是否修改依赖、配置、数据库或分支。

示例：

```text
我在项目根目录运行：
python -m demo_app.run_case schema_mismatch

最后出现：
sqlite3.OperationalError: table users has no column named user_id

预期是创建用户。请结合代码、项目文档和 Git 信息调查根因，给出文件与行号证据，不要修改代码。
```

只有 `Traceback (most recent call last):` 或单独一行源码通常不足以确定根因。当前版本尚未实现自动澄清节点，信息不足时仍可能进行过多调查。

## 15. 常见问题

### 找不到 `langgraph`

```text
ModuleNotFoundError: No module named 'langgraph'
```

请使用项目虚拟环境安装并运行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

### 找不到 `demo_app`

推荐在项目根目录使用模块方式：

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
```

`demo_app/run_case.py` 也兼容直接脚本启动。若 traceback 中导入语句仍在旧行号，可能运行的是修复前文件、未保存副本或另一个工作目录。

### 多行 traceback 被拆成多个问题

当前 `main.py` 已连续收集多行，并以空行提交。确认运行的是当前工作区的 `main.py`，粘贴结束后只额外按一次 Enter。

### Agent 调用了很多工具

一次模型响应可以同时提出多个工具调用，所以模型轮数和工具次数不同。V8.1.1 默认每轮最多真正执行 3 个外部工具，超出的调用会收到 `per_step_tool_limit`；模型需要在下一轮按信息价值重排。已有假设并取得新证据后，模型还必须先通过 `update_hypotheses` 归类证据，否则新外部调用会被控制门拒绝。confirmed 假设获得两项独立来源后会提前总结。硬预算分别限制模型和工具调用，交互模式达到软阈值则暂停询问用户。当前去重仍只识别完全相同的工具名与参数，尚未识别语义相似调查。

### Evaluation 为什么提示费用保护

一次 Profile × 一个 Case × 一次重复等于一次完整 Agent 调查，而一次调查内部可能调用模型多次。V8 默认最多免确认运行 3 次；更大的批量任务必须添加 `--yes`。建议先运行一个 Case 和一个 Profile，不要把 `--compare --runs 3 --yes` 当作烟雾测试。

### Evaluation 为什么没有触发人工审查

`run_evals.py` 是无人值守、可重复的批量评测，默认调用 `run_agent_detailed(..., human_review=False)`；否则实验会等待键盘输入，而且不同人工选择会污染 Profile 对照。因此即使达到 HITL 软阈值，Evaluation 也不会暂停，但模型和工具硬预算仍然生效。

要验证人工审查，请运行交互入口：

```powershell
.\.venv\Scripts\python.exe main.py
```

默认在模型调用达到 5 次或工具调用达到 10 次时暂停。若只想演示流程，可暂时在 `api.env` 将两个 `HITL_*_THRESHOLD` 设为 1，验证后恢复默认值；如果 Agent 在阈值前已经取得充分证据并结束，则不触发人工确认是正确行为。

### Evaluation 答案正确但没有通过

当前根因评分仍然是字面关键词规则。正确同义表达可能造成假阴性。先查看 JSON 中缺失的具体关键词，不要只看总通过率。未来将使用同义概念组和 LLM Judge 做混合评测。

### Checkpoint 在重启后丢失

当前使用 `InMemorySaver`。退出 Python 后状态消失。跨进程恢复需要 SQLite 或 PostgreSQL Checkpointer，以及能够按 thread ID 恢复的交互入口。

## 16. 当前限制

- Demo 只有六个评测案例，规模仍然太小，不能代表生产环境；
- Case、代码注释和事故文档比较明确，存在玩具数据集偏简单的问题；
- 根因关键词不理解同义词，也可能被关键词投机；
- Observation 能确认模型实际看过来源，但不能完全判断自然语言 Claim 与证据的语义蕴含关系；
- 当前没有 LLM-as-a-Judge；
- 已记录服务商返回的 Token，但尚未根据不同模型价格计算真实金额；服务商不返回 usage 时 Token 显示 0；
- Observation 只保存最多 1000 字符结果摘要和 SHA-256，完整工具内容主要保留在 LangGraph 消息状态中；
- 发给模型的压缩记忆将每个 Observation 摘要限制为 700 字符；普通调查只保留所有已引用证据和最近 4 条未引用结果，最终报告阶段则恢复全部带来源的成功结果。长结果中的次要细节仍可能被省略，但本地 Checkpoint 中的完整消息不会被删除；
- 上下文压缩的实际 Token 节省依赖模型服务是否返回 usage，必须通过同一 Case 的真实 V8/V8.1.1 对照确认，离线测试不能证明具体节省比例；
- `confidence` 是模型自我声明，不是校准后的概率；
- `InMemorySaver` 不能跨进程恢复；
- 已有确定性假设 Gate，但“两个独立来源”是工程启发式，不等于自然语言语义蕴含证明；
- HITL 目前只在同一 Python 进程内恢复，也不会授权绕过评测和敏感路径隔离；
- CLI 每次运行最多触发一次人工决策，尚未实现多阶段审批策略；
- 没有安全命令执行、补丁生成与修复验证；
- 没有 Web UI 或服务端 API。

## 17. 后续规划

推荐顺序：

1. 用同一个单案例低成本实验建立 V8/V8.1.1 的准确性、工具调用、Token、Observation 利用率和早停对照；
2. 将 `InMemorySaver` 替换为 SQLite/PostgreSQL Checkpointer，支持进程重启后按 thread ID 恢复；
3. 在任何执行命令和修改文件能力之前增加独立人工审批；
4. 增加受限命令执行，用真实 Runtime Evidence 自动复现；
5. 增加补丁提议、人工批准、应用补丁和测试验证；
6. 将本地确定性规则与 LLM Judge 组合，并增加真实费用和多模型对比；
7. 扩展隐藏评测集，分离开发集与测试集。

Human-in-the-loop 必须早于任何自动执行或修改能力。否则 Agent 在证据不足或判断错误时可能直接产生有副作用的操作。

## 18. 面试讲解版本

一句话：

> IncidentPilot 是一个基于 LangGraph 的只读、成本感知、假设与证据驱动 Python 故障诊断 Agent。它用结构化下一步动作和单轮工具上限控制调查宽度，用压缩调查记忆降低重复输入 Token；只有 confirmed 假设获得独立 Observation 才提前总结。最终 Claim 必须绑定真实 Evidence，并通过文件行号、RAG Chunk 或 Git Commit 验证来源。成本阈值或冲突会用原生 interrupt 暂停，由用户决定继续、总结或取消。

完整流程：

> 用户提交完整 traceback 后，模型先通过内部控制工具保存候选 Hypothesis，并为未确认假设声明一项可证伪的下一步动作。每轮只执行有限数量的高信息价值只读工具；完整状态留在 Checkpoint，而模型请求只携带当前假设、被引用证据和最近未分类证据。系统拒绝不存在和失败的 Observation 引用；confirmed 假设必须获得至少两项独立来源才触发早停。达到费用阈值、保护路径或假设冲突时，LangGraph `interrupt()` 保存 checkpoint，用户决策通过 `Command(resume=...)` 恢复。最终 Claim—Evidence Ledger 还要经过 Pydantic 和 Provenance 双重验证。Evaluation 同时衡量准确性、证据落地、上下文压缩、Observation 利用率、早停、Token、工具贡献和稳定性，并在批量真实调用前执行费用保护。

## 19. 文档维护规则

以后每次升级版本必须同步维护：

- `README.md`：只保留新版本当前真实存在的完整说明，更新版本号、结构、命令、数据流、限制、测试数量和后续规划；
- `CHANGELOG.md`：新增该版本的“新增、修改、修复、安全、验证和兼容性”记录。

不要再把旧版本实现说明连续追加到 README。历史原因、迁移过程和版本差异统一放入 CHANGELOG；当前使用者只需要阅读 README。
