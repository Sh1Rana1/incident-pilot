# IncidentPilot V4：LangGraph + 本地 RAG + Git Tools

IncidentPilot 是一个用于排查 Python 项目故障的最小 Agent。

用户把错误日志和问题交给它以后，模型不会直接读取硬盘。它会选择本地工具来搜索代码、读取文件、收集证据；当证据足够时，再输出根因、证据和修复建议。

当前版本只负责**调查和提出建议**，不会运行目标项目，也不会修改代码。V4 在 LangGraph 状态图上加入本地知识库 RAG 和三个只读 Git 调查工具。

## 0. 我们的开发约定

从现在开始，每次修改项目时，都必须同步更新本 README，至少说明：

1. 增加、修改或删除了什么；
2. 为什么这样设计；
3. 怎样安装、配置、运行和验证；
4. 数据怎样在代码之间流动；
5. 当前限制和下一步是什么。

目标不是只让 AI 写出能跑的代码，而是让你可以解释整个项目。

## 1. 当前版本能做什么

Agent 目前有两个工具：

- `search_code(query)`：搜索项目中的关键词，返回文件、行号和命中内容；
- `read_file(path)`：读取项目内的 UTF-8 文本文件，返回带行号的内容。

典型调查过程如下：

```text
用户错误日志
    ↓
模型提取 traceback、异常名、变量名等线索
    ↓
模型请求 search_code("user_id")
    ↓
Python 在本地搜索并返回候选文件
    ↓
模型请求 read_file("app/service.py")
    ↓
Python 返回代码上下文
    ↓
模型继续搜索调用方，或在证据充足后给出结论
```

## 2. 它怎样找到错误所在的文件

Agent 一开始并不知道错误在哪个文件。文件位置通常来自两类线索。

### 2.1 traceback 直接给出位置

完整 traceback 可能包含：

```text
File "app/service.py", line 32, in process_user
    user_id = data["user_id"]
KeyError: 'user_id'
```

它直接提供了候选文件、行号、函数名和出错表达式。模型随后可以请求读取 `app/service.py`。

### 2.2 根据关键词搜索

如果日志没有明确文件名，但出现了 `user_id`、函数名或特殊错误文本，模型可以请求：

```text
search_code("user_id")
```

本地工具可能返回：

```text
app/service.py:32: user_id = data["user_id"]
app/api.py:17: process_user(request.json)
```

这只是候选位置，不等于根因已经确定。模型还需要读取文件，理解变量来源、调用关系和输入校验。

所以它的定位方式是：

```text
模型选择调查动作 + Python 工具实际搜索硬盘 + 模型解释结果
```

## 3. 项目结构

```text
incident-pilot/
├── .gitignore          # 忽略密钥、虚拟环境和缓存
├── api.env.example     # API 配置模板，不含真实密钥
├── requirements.txt    # Python 第三方依赖
├── main.py             # 命令行入口
├── agent.py            # Agent Loop：连接模型、消息和工具
├── tools.py            # 本地工具及其 JSON 说明
├── test_tools.py       # 不消耗 API 的离线测试
└── README.md           # 项目手册和更新记录
```

### `main.py`：用户界面层

它等待用户输入，调用 `run_agent(question)`，显示最终结论，并处理退出和异常。它不负责分析根因。

### `agent.py`：循环控制层

它负责读取 API 配置、创建客户端、保存消息历史、请求模型、执行模型选中的工具，并持续循环直到得到最终答案或达到步数上限。

### `tools.py`：本地能力层

模型不能直接读取你的硬盘。真正访问文件的是这里的普通 Python 函数。

`TOOL_FUNCTIONS` 把模型说出的工具名映射到真实函数：

```python
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "search_code": search_code,
}
```

`TOOL_SCHEMAS` 是给模型看的工具说明书，其中声明了工具名称、用途、参数类型和必填参数。模型看到说明书并选择工具，Python 程序才真正执行函数。

### `test_tools.py`：离线验证层

它检查读取文件、搜索关键词、阻止越界路径和未知工具处理。这些测试不请求模型，不花 API 额度。

## 4. API 配置

参考 `api.env.example`，在项目根目录新建 `api.env`：

```env
API_KEY=你的真实密钥
BASE_URL=https://api.openai.com/v1
MODEL=gpt-5.4-mini
```

| 配置 | 必填 | 含义 |
|---|---:|---|
| `API_KEY` | 是 | 服务商提供的访问密钥 |
| `BASE_URL` | 否 | API 地址；不填时使用 OpenAI 官方地址 |
| `MODEL` | 是 | 你的账户可用且支持 Tool Calling 的模型名 |

第三方服务需要填写其提供的 `BASE_URL` 和 `MODEL`。支持普通聊天不代表一定完整兼容 Tool Calling。

真实的 `api.env` 已被 `.gitignore` 排除，不应上传到 GitHub 或发给别人。

## 5. 第一次安装和运行

在 PowerShell 中依次执行：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

这些步骤分别用于：

1. 创建隔离的 Python 虚拟环境；
2. 激活它；
3. 安装 `openai` 和 `python-dotenv`；
4. 启动命令行 Agent。

启动后粘贴完整 traceback 和问题。输入 `exit` 或 `quit` 退出。

## 6. Agent Loop 完整原理

核心入口是：

```python
run_agent(user_input, max_steps=8)
```

### 第一步：加载配置

`create_client()` 从 `api.env` 读取 `API_KEY`、`BASE_URL` 和 `MODEL`。缺少必填项时会明确报错，并且不会请求 API。

### 第二步：建立消息历史

初始历史包含：

```text
system：规定 Agent 的身份、目标和只读边界
user：用户提交的错误日志和问题
```

第一版的“记忆”就是内存中的 `messages` 列表。程序退出后不会永久保存。

### 第三步：请求模型做决定

程序把消息历史、工具说明和 `tool_choice="auto"` 一起发给模型。模型可以直接回答，也可以提出工具调用：

```json
{
  "name": "search_code",
  "arguments": {"query": "user_id"}
}
```

此时模型只表达了意图，还没有搜索文件。

### 第四步：执行工具

`execute_tool()` 根据名称找到 Python 函数，将 JSON 参数转成字典，然后调用函数。参数或执行出错时，错误文本也会作为观察结果返回给模型。

### 第五步：返回观察结果

工具结果会作为 `role="tool"` 消息加入历史，并通过 `tool_call_id` 与刚才的工具请求对应。下一轮模型能看到此前的请求和结果，从而决定继续读文件、继续搜索或结束调查。

### 第六步：结束

以下情况会停止循环：

1. 模型不再请求工具，普通文本成为最终结论；
2. 达到 8 步上限，防止无限循环和费用失控；
3. API 或程序发生异常，由 `main.py` 显示错误。

完整的数据流是：

```text
main.py 接收问题
    ↓
agent.py 把消息和工具定义交给模型
    ↓
模型返回工具名称与 JSON 参数
    ↓
agent.py 调用 tools.py 中的真实函数
    ↓
工具结果加入 messages
    ↓
再次请求模型，直到返回最终文本
    ↓
main.py 显示答案
```

## 7. 两个工具的详细行为

### `read_file(path)`

- 把路径理解为项目根目录下的相对路径；
- 确认最终路径仍在项目内部；
- 拒绝 `../outside.txt` 之类的越界读取；
- 按 UTF-8 读取并添加行号；
- 最多返回 20,000 个字符；
- 拒绝二进制或非 UTF-8 文件。

### `search_code(query)`

它递归搜索以下文件：

```text
.py .md .txt .json .toml .yaml .yml
```

它忽略：

```text
.git .venv __pycache__ node_modules
```

搜索不区分大小写，最多返回 50 条结果。它目前只是字符串匹配，不理解 Python 抽象语法树。

## 8. 当前安全设计

- `api.env` 不提交到 Git；
- 文件工具只能访问项目内部；
- Agent 没有写文件和执行命令的工具；
- 循环最多执行 8 步；
- 大文件和大量结果会被截断；
- 工具错误会成为可见结果，而不是直接导致程序崩溃。

后面如果增加运行代码或修改文件的能力，还需要更严格的超时、审批和隔离。

## 9. 怎样提问效果最好

尽量一次提供：

1. 完整 traceback；
2. 执行了什么命令或操作；
3. 预期发生什么；
4. 实际发生什么；
5. 问题能否稳定复现。

示例：

```text
我执行 python app.py，然后调用 POST /users 时报错：

Traceback (most recent call last):
  File "app/service.py", line 32, in process_user
    user_id = data["user_id"]
KeyError: 'user_id'

预期接口返回新用户。每次提交不带 user_id 的请求都会复现。
请找到根因，并给出文件、行号和修复建议。
```

## 10. 测试

运行不需要 API 的测试：

```powershell
python -m unittest -v
```

当前 4 个测试为：

- `test_read_file`；
- `test_search_code`；
- `test_cannot_escape_project`；
- `test_unknown_tool`。

它们证明本地工具的基础行为正常，但不代表所有模型和第三方 API 都兼容。

## 11. 常见问题

### 提示 `api.env 缺少配置`

确认根目录存在 `api.env`，并填写了 `API_KEY` 和 `MODEL`。

### 提示没有 `openai` 或 `dotenv` 模块

激活虚拟环境后执行：

```powershell
python -m pip install -r requirements.txt
```

### 模型直接猜答案，没有搜索

提供完整 traceback，并确认模型支持 Tool Calling。提示词能引导行为，但不能绝对保证模型每次选择相同动作。

### 搜索不到代码

确认目标代码位于当前项目目录内，并且文件扩展名在支持列表中。

### 第三方 API 调用失败

核对密钥、地址、模型名和 Tool Calling 兼容性。

## 12. 当前局限

当前 Agent：

- 不会自动运行项目或测试；
- 不会查看 Git 改动；
- 不会列出完整项目树；
- 不会修改代码；
- 没有数据库或长期记忆；
- 只做字符串搜索，不理解语法树；
- 不能保证一定找到真实根因；
- 只能调查当前 `incident-pilot` 目录内的代码。

## 13. 下一步建议

下一小步建议增加 `list_files` 工具，让 Agent 在线索不足时先了解项目结构。之后再逐步考虑：

1. 专门的日志读取工具；
2. 更清晰的调查轨迹展示；
3. 防止重复调用同一工具；
4. 更明确的调用预算；
5. 受限制的测试运行工具；
6. 最后才加入代码修改和人工审批。

我们会保持“小步实现、小步测试、小步讲解”。

## 14. 更新记录

### V1 初始版本

- 实现最小 Agent Loop；
- 增加 `read_file` 与 `search_code`；
- 增加 OpenAI 兼容 API 配置；
- 增加路径边界和结果截断；
- 增加 4 个离线测试。

### V1 文档扩充

- 确立每次改动同步维护 README 的约定；
- 补充项目结构、代码职责、完整数据流和运行说明；
- 补充安全设计、提问示例、常见问题、局限和路线图。

### V2 工具与输出工程化

- 新增 `models.py`，集中定义数据契约；
- 新增 `registry.py`，集中完成工具注册、Schema 生成、参数校验和调用分发；
- `read_file` 与 `search_code` 改为装饰器注册；
- 新增安全的 `list_files`；
- 所有工具统一返回 `ToolResult` JSON；
- 最终答案改为 JSON Schema 约束的 `IncidentReport`；
- `main.py` 把结构化报告渲染成中文文本；
- 离线测试由 4 个增加到 10 个；
- 类型写法兼容当前 Python 版本。

## 16. V2 升级详解

> 前面章节保留了 V1 的基础原理，便于理解 Agent Loop。下面是当前 V2 的实际架构；如有冲突，以本章为准。

### 16.1 新的项目结构

```text
incident-pilot/
├── main.py       # 接收问题，把报告格式化给人看
├── agent.py      # Agent Loop 与 API 调用
├── models.py     # 工具结果、证据、最终报告的数据模型
├── registry.py   # 工具注册、Schema 生成、校验、分发
├── tools.py      # read_file、search_code、list_files
└── test_tools.py # 10 个离线测试
```

### 16.2 统一工具注册

V1 需要分别维护函数、`TOOL_FUNCTIONS` 和 `TOOL_SCHEMAS`。V2 用一个装饰器把函数和元数据放在一起：

```python
@registry.register(
    name="search_code",
    description="在项目代码和文本文件中搜索关键词",
    arguments_model=SearchCodeArgs,
)
def search_code(arguments: SearchCodeArgs) -> ToolResult:
    ...
```

注册器会自动：

1. 保存工具名到函数的映射；
2. 从 Pydantic 参数模型生成 JSON Schema；
3. 给 API Schema 开启严格模式；
4. 在执行前校验模型提供的参数；
5. 捕获错误并转换为统一结果。

增加新工具时，只需要定义参数模型、写函数并添加装饰器，不再手写另一份容易不一致的 Schema。

### 16.3 工具参数校验

例如 `list_files` 使用：

```python
class ListFilesArgs(StrictModel):
    path: str
    max_depth: int  # 必须在 1 到 5 之间
```

模型如果漏掉字段、传错类型、加入未知字段，注册器不会执行工具，而会返回结构化校验错误。`StrictModel` 的 `extra="forbid"` 用于拒绝未声明参数。

### 16.4 统一工具结果

三个工具现在都返回同一个信封：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "truncated": false
  }
}
```

- `ok`：调用是否成功；
- `data`：成功时的业务数据；
- `error`：失败原因；
- `meta`：命中数量、截断状态、深度等辅助信息。

模型不再需要猜测每个工具不同的文本格式，程序也能稳定地区分成功和失败。

### 16.5 `list_files` 工具

调用参数示例：

```json
{"path": ".", "max_depth": 3}
```

返回的每一项包含相对路径和类型：

```json
{
  "path": "app/service.py",
  "type": "file"
}
```

它适用于 traceback 没有文件名、又缺少有效搜索词的情况。模型可以先认识项目结构，再选择入口文件、配置或相关模块。

安全与容量限制：

- 只能查看项目内部；
- 深度必须是 1 到 5；
- 最多返回 200 项；
- 忽略 `.git`、`.venv`、缓存、依赖和构建目录；
- 隐藏 `api.env`、`.env` 等敏感文件。
- `list_files` 同时忽略 `.incident_cache`，避免内部索引污染项目结构结果。

### 16.6 结构化最终报告

最终回答不再只是提示词约定的自由文本，而必须符合 `IncidentReport`：

```json
{
  "summary": "一句话调查摘要",
  "root_cause": "根因或证据不足说明",
  "evidence": [
    {
      "file": "app/service.py",
      "line": 32,
      "description": "直接访问缺失的 user_id"
    }
  ],
  "suggested_fixes": ["在接口入口校验必填字段"],
  "confidence": "high"
}
```

这里有两层保障：

1. API 请求携带 JSON Schema，约束模型生成格式；
2. 返回后再由 Pydantic 本地验证，拒绝缺字段、错类型和非法置信度。

`main.py` 的 `format_report()` 最后把这个 JSON 对象转换成适合人阅读的“摘要、根因、证据、修复建议、置信度”。数据格式与显示格式因此彼此分离。

### 16.7 V2 完整数据流

```text
main.py 获取用户问题
    ↓
agent.py 加载消息历史、工具 Schema、报告 Schema
    ↓
模型选择工具，并生成 JSON 参数
    ↓
registry.py 用 Pydantic 校验参数
    ↓
tools.py 执行只读操作，返回 ToolResult
    ↓
ToolResult JSON 加入 messages，再次请求模型
    ↓
模型生成 IncidentReport JSON
    ↓
models.py 在本地再次验证
    ↓
main.py 格式化并显示
```

### 16.8 V2 测试

运行：

```powershell
python -m unittest -v
```

当前 10 个测试覆盖：

- 三个工具是否完成注册；
- API 工具 Schema 是否为严格模式；
- 未知工具是否返回标准错误；
- 错误参数是否被 Pydantic 拦截；
- 文件读取、代码搜索和目录枚举；
- 越界路径和敏感配置是否被拦截；
- 最终报告是否可以稳定渲染。

### 16.9 V2 兼容性说明

`requirements.txt` 现在显式包含 Pydantic 2。第三方 OpenAI 兼容服务除了支持 Tool Calling，还必须支持 Chat Completions 的 JSON Schema Structured Outputs；否则真实请求可能被服务商拒绝。

当前离线测试全部通过，但尚未使用你的密钥发送真实 API 请求。

### 16.10 下一步

建议先构造一个很小的“故障示例项目”，使用你的 API 做第一次端到端测试，观察 Agent 是否会按顺序调用 `list_files`、`search_code`、`read_file` 并输出合格报告。确认 V2 主链路后，再增加日志读取或受限制的测试执行工具。

## 17. DeepSeek V4 配置

如果使用 DeepSeek V4 Pro，在根目录的 `api.env` 中填写：

```env
API_KEY=替换为你的DeepSeek_API_Key
BASE_URL=https://api.deepseek.com/beta
MODEL=deepseek-v4-pro
```

如果希望优先考虑速度和成本，把模型改为：

```env
MODEL=deepseek-v4-flash
```

这里使用 `/beta`，是因为 V2 生成的工具定义包含 `strict: true`，DeepSeek 官方要求严格工具调用通过 Beta 地址使用。

项目现已自动识别 DeepSeek：最终输出使用 `json_object`，工具严格模式在 `/beta` 地址下开启，返回后继续由 Pydantic 做本地严格校验。之前的 `This response_format type is unavailable now` 错误已经从配置兼容层解决。

## 18. 只改 `api.env` 切换模型服务

新增的 `config.py` 把供应商差异集中在配置层。最简单的情况下，`api.env` 仍然只需要三项：

```env
API_KEY=你的密钥
BASE_URL=服务商的OpenAI兼容地址
MODEL=服务商提供的模型ID
```

自动模式规则：

| 服务 | 最终输出模式 | 严格工具模式 |
|---|---|---|
| OpenAI 官方地址 | `json_schema` | 开启 |
| DeepSeek 普通地址 | `json_object` | 关闭 |
| DeepSeek `/beta` 地址 | `json_object` | 开启 |
| 其他 OpenAI 兼容地址 | `json_object` | 关闭 |

其中 `json_schema` 由服务端严格保证最终字段结构；`json_object` 保证合法 JSON，再由本地 Pydantic 检查具体字段。

如果某个兼容服务能力特殊，可以仅在 `api.env` 增加覆盖项：

```env
# auto / json_schema / json_object / text
OUTPUT_MODE=auto

# auto / true / false
STRICT_TOOLS=auto
```

- 服务不接受 `json_object` 时，设置 `OUTPUT_MODE=text`；程序仍会要求模型只输出 JSON，并在本地校验；
- 服务明确支持 JSON Schema 时，设置 `OUTPUT_MODE=json_schema`；
- 服务不接受工具中的 `strict` 字段时，设置 `STRICT_TOOLS=false`；
- 服务支持严格工具 Schema 时，可以设置 `STRICT_TOOLS=true`。

如果模型第一次返回的 JSON 不符合 `IncidentReport`，Agent 不会直接崩溃，而会把简短的校验错误放回消息历史，要求模型在剩余步数内重新输出。

### DeepSeek V4 推荐配置

```env
API_KEY=你的DeepSeek_API_Key
BASE_URL=https://api.deepseek.com/beta
MODEL=deepseek-v4-pro
OUTPUT_MODE=auto
STRICT_TOOLS=auto
```

`deepseek-v4-flash` 只需替换 `MODEL`。不要把真实密钥写进 `api.env.example`。

### 本次兼容层更新

- 新增 `config.py`；
- 自动识别 OpenAI、DeepSeek 和通用兼容服务；
- 输出模式支持 `json_schema`、`json_object`、`text`；
- 工具严格模式可自动选择或手动覆盖；
- 最终 JSON 本地校验失败时自动请求模型重试；
- 恢复不含密钥的 `api.env.example`；
- 离线测试由 10 个增加到 14 个。

## 19. V3：迁移到 LangGraph

### 19.1 迁移目标

V2 使用 `for` 循环和 `if` 判断控制模型、工具与报告验证。V3 不改变业务能力，只把控制流显式建模为 LangGraph：

```text
START
  ↓
call_model
  ↓
route_after_model
  ├── 有工具调用 → execute_tools ─────────→ call_model
  ├── 最终文本   → validate_report
  │                    ├── 合格 ───────────→ END
  │                    └── 不合格 ─────────→ call_model
  └── 预算耗尽   → build_fallback ─────────→ END
```

这次迁移刻意保留：

- `config.py` 的多模型兼容配置；
- `registry.py` 的工具注册与参数校验；
- `tools.py` 的三个只读工具；
- `models.py` 的 `ToolResult` 和 `IncidentReport`；
- `main.py` 的命令行交互与报告渲染。

主要变化是用 `graph.py` 替代 `agent.py` 中的手写循环。这样可以清楚比较“原生循环”和“状态图”两种实现，而不是推倒重写。

### 19.2 Python 与安装环境

LangGraph V3 使用 Python 3.10+。本机项目虚拟环境已经使用 Python 3.14 创建。

首次安装：

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`requirements.txt` 新增：

```text
langgraph>=1.0.0,<2.0.0
```

实际验证安装的版本是 LangGraph 1.2.11。使用版本范围而不是无限制最新版，是为了允许 1.x 的兼容更新，同时避免未来 2.x 破坏性变化被自动安装。

### 19.3 新增 `graph.py`

这个文件包含五部分：

1. `AgentState`：图中所有节点共享的数据；
2. 四个节点：模型、工具、验证和降级报告；
3. 两个条件路由函数；
4. `build_agent_graph()`：组装节点和边；
5. 模型消息到普通字典的转换。

`agent.py` 现在只保留面向外部的 `run_agent()`，负责加载配置、创建客户端、初始化状态、设置 thread ID、调用图并返回报告。

### 19.4 AgentState：图的共享状态

```python
class AgentState(TypedDict):
    messages: Annotated[list[dict], operator.add]
    step_count: int
    tool_call_count: int
    max_steps: int
    report: Optional[dict]
    validation_error: Optional[str]
    stop_reason: Optional[str]
```

字段含义：

| 字段 | 作用 |
|---|---|
| `messages` | 保存系统消息、用户问题、模型回复和工具结果 |
| `step_count` | 已经请求模型的次数 |
| `tool_call_count` | 已经执行的工具数量 |
| `max_steps` | 本次调查最多允许请求模型多少次 |
| `report` | 验证成功或降级生成的最终报告 |
| `validation_error` | 上一次报告格式错误的简短原因 |
| `stop_reason` | `completed` 或 `max_steps` |

`messages` 使用 `Annotated[..., operator.add]` 作为 reducer。节点返回新消息时，LangGraph 会将其追加到历史，而不是覆盖全部历史。其他字段不使用 reducer，节点返回新值时直接覆盖旧值。

### 19.5 四个节点

#### `call_model`

读取 `messages` 和配置，向模型发送工具 Schema 与输出格式，然后把模型响应追加到状态，并增加 `step_count`。

SDK 返回的消息先通过 `assistant_message_to_dict()` 转成普通字典。这样路由函数容易检查 `tool_calls`，checkpoint 也不需要保存供应商 SDK 的复杂对象。DeepSeek 返回的额外消息字段也会随 `model_dump()` 保留下来。

#### `execute_tools`

读取最后一条模型消息中的全部 `tool_calls`，继续通过原有 `registry.execute()` 校验和执行，并把每个结果追加为对应的 `role="tool"` 消息。

V3 没有直接采用预构建 `ToolNode`，原因是我们已经有统一的注册器、Pydantic 参数校验和 `ToolResult` 格式。先保留这些代码，可以让本次迁移只聚焦控制流。

#### `validate_report`

当模型没有请求工具时，这个节点使用 `IncidentReport.model_validate_json()` 检查最终文本：

- 验证成功：写入 `report`，并设置 `stop_reason="completed"`；
- 验证失败：记录 `validation_error`，追加一条纠错消息，再回到模型节点。

#### `build_fallback`

达到 `max_steps` 时，生成低置信度报告并设置 `stop_reason="max_steps"`，保证图总能以明确结果结束。

### 19.6 两个条件路由

`route_after_model()` 检查模型是否请求工具以及预算是否耗尽，选择：

```text
execute_tools / validate_report / build_fallback
```

`route_after_validation()` 检查报告是否通过验证，选择：

```text
END / call_model / build_fallback
```

路由函数不访问网络、不执行工具，只根据状态做决定，因此可以独立进行确定性测试。

### 19.7 Checkpoint 与 thread ID

V3 使用：

```python
CHECKPOINTER = InMemorySaver()
```

调用图时会传入：

```python
{"configurable": {"thread_id": "..."}}
```

LangGraph 会在执行步骤之间保存该线程的状态快照，为以后实现中断恢复、人工审批和调试打基础。

当前限制：`InMemorySaver` 只保存在当前 Python 进程内，程序退出后 checkpoint 会丢失。未来需要跨进程恢复时，应换成 SQLite 或 PostgreSQL checkpointer。

每次 `run_agent()` 默认生成新的 UUID，避免不同问题意外共享消息。也可以显式传入 `thread_id`，但当前命令行界面还没有实现“继续旧调查”的交互。

### 19.8 预算与递归限制

业务预算仍由 `max_steps` 控制，它计算模型请求次数。LangGraph 另外设置：

```python
recursion_limit = max_steps * 3 + 5
```

这是框架层的保险，因为一次模型调查可能经过模型节点、工具节点和验证节点多个图步骤。业务预算与图递归上限职责不同：前者控制模型花费，后者防止图结构意外无限执行。

### 19.9 测试

测试命令：

```powershell
.venv\Scripts\python.exe -m unittest -v
```

V3 当前共有 20 项离线测试。新增 6 项覆盖：

- 有工具调用时路由到工具节点；
- 合格报告路由到结束；
- 预算耗尽路由到降级节点；
- 假模型先调用工具、再返回合格报告；
- 假模型先返回错误格式、收到纠错后重新生成；
- 最大步数下生成低置信度报告。

假模型会记录收到的请求并按预设顺序返回结果，所以这些测试不访问网络、不消耗 API，而且可以确定性验证整张图。

### 19.10 当前验证状态

- LangGraph 1.2.11 已安装到项目 `.venv`；
- 原有 14 项测试全部继续通过；
- 新增 6 项图测试全部通过；
- 总计 20 项离线测试通过；
- 代码已通过编译检查；
- 尚未执行真实 DeepSeek 端到端测试。

真实测试没有自动执行，是因为 Agent 可能把项目结构和读取到的代码片段发送给外部模型服务。只有在明确授权发送当前项目数据后，才应执行该测试。

### 19.11 V3 仍未包含的能力

- checkpoint 落盘；
- 从旧 thread 恢复的命令行入口；
- 重复工具调用检测；
- Token、费用和运行时间预算；
- LangSmith tracing；
- 人工审批节点；
- 自动运行测试；
- 自动修改代码。

下一步建议先进行一次明确授权的 DeepSeek 端到端测试，再实现“重复工具调用检测 + 调查轨迹”。

## 20. 如何完整讲解这张 Graph

### 20.1 一句话版本

> IncidentPilot 将故障调查建模成一张有状态的循环图：模型节点决定下一步，工具节点收集证据，验证节点检查最终报告，条件边根据共享状态决定继续调查、重新生成还是结束。

### 20.2 一分钟面试版本

> 项目最初使用原生 Python 的 `for` 循环实现 Agent Loop。随着工具调用、格式验证和预算控制增加，我把控制流迁移到 LangGraph。
>
> 图中有四个节点：`call_model`、`execute_tools`、`validate_report` 和 `build_fallback`。模型如果返回工具调用，条件边就进入工具节点；工具节点通过自定义 Registry 校验参数、执行只读工具，并将结果作为 Tool Message 写回消息历史，然后再次调用模型。
>
> 如果模型没有调用工具，流程进入报告验证节点。Pydantic 验证成功后结束；验证失败则追加纠错消息并返回模型重试。达到模型调用预算时，降级节点生成低置信度报告并受控结束。消息、调用次数、报告和停止原因都保存在 `AgentState` 中，并由 `InMemorySaver` 保存步骤级 checkpoint。

### 20.3 从输入到输出的完整过程

1. `agent.py` 接收用户问题，创建初始 `AgentState`；
2. `START` 固定进入 `call_model`；
3. 模型接收消息历史、工具 Schema 和最终输出格式；
4. `route_after_model` 检查模型是否生成 `tool_calls`；
5. 有工具调用时，`execute_tools` 通过 Registry 校验并执行工具；
6. 工具结果携带 `tool_call_id` 追加到 `messages`；
7. 固定边将流程送回 `call_model`，形成 Decision → Action → Observation 循环；
8. 模型不再调用工具时，进入 `validate_report`；
9. Pydantic 验证合格后写入 `report` 并结束；
10. 验证失败时追加纠错消息并重试；
11. 达到 `max_steps` 时进入 `build_fallback`，生成低置信度报告后结束；
12. `main.py` 将结构化 `IncidentReport` 渲染成人类可读文本。

### 20.4 Reducer 为什么重要

`messages` 的声明是：

```python
messages: Annotated[list[dict], operator.add]
```

`operator.add` 是该字段的 reducer。节点返回：

```python
{"messages": [new_message]}
```

LangGraph 会把新消息追加到旧消息，而不是覆盖历史。模型因此能看到此前的用户问题、工具请求和观察结果。`step_count` 等其他字段没有 reducer，所以节点返回的新值会直接覆盖旧值。

### 20.5 为什么工具结果需要 `tool_call_id`

模型一次可能生成多个工具调用。每条工具结果都包含对应的 `tool_call_id`，用于明确说明“这条 Observation 对应哪次 Action”。缺少或对应错误时，模型 API 可能认为消息历史不合法。

### 20.6 为什么把报告验证拆成节点

是否符合 JSON Schema 是确定性问题，不应该让模型自己判断。拆成 `validate_report` 后，图能明确表达三种结果：

```text
验证成功 → END
验证失败且有预算 → call_model
验证失败且预算耗尽 → build_fallback
```

验证逻辑也能脱离真实模型单独测试。

### 20.7 两层循环保护

- `max_steps` 是业务预算，统计模型调用次数，主要限制 API 成本和调查长度；
- `recursion_limit` 是 LangGraph 的框架保险，限制图节点总执行步数。

一次模型调查可能经过模型、工具和验证等多个节点，因此图步数通常大于模型调用次数，两者不能简单设置成同一个值。

### 20.8 Checkpoint 的准确含义

`InMemorySaver` 按 `thread_id` 保存图步骤之间的状态快照。它为状态查看、中断恢复和人工审批提供基础，但不是永久存储：Python 进程退出后数据会消失。

当前每个新问题默认生成独立 UUID，避免不同调查意外共享消息。未来若要跨进程恢复，需要使用 SQLite 或 PostgreSQL checkpointer，并在命令行或 Web 层提供继续指定 thread 的入口。

### 20.9 常见追问与回答

#### 为什么不直接使用 LangGraph 的 `ToolNode`？

> V2 已经实现了统一工具注册、Pydantic 参数校验和 `ToolResult`。V3 的目标是单独迁移控制流，因此保留自己的工具层，减少同时变化的变量。后续可以再将它与预构建 `ToolNode` 做对比。

#### LangGraph 是否让模型更聪明？

> 不会。LangGraph改善的是状态管理、控制流、恢复能力和可测试性。调查质量仍由模型能力、工具设计、上下文质量和评测决定。

#### 为什么节点只返回局部状态？

> 每个节点只声明自己的修改，职责更清楚；LangGraph 再按照字段 reducer 合并更新，并在节点边界创建 checkpoint。

#### 为什么把 SDK 消息转换成普通字典？

> 普通字典更容易检查、测试和序列化，也能降低图状态对单一模型供应商 SDK 类型的耦合。

#### 当前持久化有什么不足？

> `InMemorySaver` 不能跨进程恢复，也没有处理长期存储的并发、清理和生命周期问题。当前只用于学习和验证 checkpoint 机制。

### 20.10 最值得记住的总结

> LangGraph 没有替项目实现业务能力，而是把原本隐藏在 `for` 循环和 `if` 判断中的 Agent 控制流，变成了可观察、可测试、可扩展、可 checkpoint 的状态图。

## 21. V4：本地 RAG 与 Git Tools

### 21.1 V4 解决什么问题

此前 Agent 只能回答“代码实际上怎么写”。V4 新增两类证据：

```text
代码工具 → 当前代码实际上怎么写
RAG      → 项目文档规定应该怎么做
Git 工具 → 最近发生了什么变化
LLM      → 综合三类证据判断根因
```

例如 `KeyError: user_id` 调查可以组合：

- `api.md`：`user_id` 是必填字段；
- `api.py`：请求入口没有验证字段；
- `service.py`：直接使用 `data["user_id"]`；
- `git_diff`：最近删除了字段校验。

这比只搜索代码更接近真实故障调查。

### 21.2 V4 项目结构

```text
incident-pilot/
├── graph.py                   # LangGraph 状态图
├── registry.py                # 统一工具注册和参数校验
├── tools.py                   # 文件与代码工具
├── retrieval.py               # Markdown 切块、向量化、缓存和检索
├── knowledge_tools.py         # retrieve_docs 工具
├── git_tools.py               # 三个只读 Git 工具
├── knowledge/
│   ├── database.md            # 数据与持久化约定
│   ├── api.md                 # 模型 API 与工具协议
│   └── troubleshooting.md    # 已知故障和解决方法
├── .incident_cache/           # 自动生成的 RAG 索引，不提交 Git
├── test_graph.py
└── test_tools.py
```

### 21.3 当前七个工具

| 类别 | 工具 | 用途 |
|---|---|---|
| 代码 | `list_files` | 查看有限深度的项目结构 |
| 代码 | `search_code` | 根据关键词寻找代码位置 |
| 代码 | `read_file` | 读取带行号的文件内容 |
| RAG | `retrieve_docs` | 从 `knowledge/` 返回最相关文档片段 |
| Git | `git_status` | 查看分支和工作区状态 |
| Git | `git_diff` | 查看指定路径的未提交差异 |
| Git | `git_log` | 查看有限数量的最近提交 |

所有工具仍然经过同一个 `execute_tools` LangGraph 节点。节点代表“工具执行阶段”，不必为每个工具创建单独节点。

### 21.4 RAG 是什么

RAG 是 Retrieval-Augmented Generation，即检索增强生成：

```text
用户问题
   ↓
从私有知识库检索相关片段
   ↓
把片段作为 Tool Message 交给模型
   ↓
模型基于检索证据生成报告
```

模型参数中不包含本项目的内部约定。RAG 让 Agent 在回答前按需取得这些外部知识，而不是要求用户每次把全部文档粘贴进问题。

V4 采用 Agentic RAG：是否调用 `retrieve_docs`、检索什么问题、需要几条结果，都由模型根据当前调查状态决定。RAG 没有成为独立图节点，而是注册为普通工具，因此可以自然加入现有 Agent Loop。

### 21.5 文档摄取与切块

`retrieval.py` 只扫描 `knowledge/**/*.md`。`split_markdown()` 首先按照 Markdown 标题划分章节，同时保留：

- `source`：文档相对路径；
- `section`：章节标题；
- `line_start`：章节起始行；
- `content`：片段正文；
- `chunk_id`：由来源和内容生成的稳定 ID。

章节超过 900 字符时继续使用滑动窗口切分，相邻窗口保留 120 字符重叠。这样既避免片段过大，也降低答案刚好跨越切分边界时的信息丢失。

### 21.6 当前本地向量方法

V4 没有下载大型 Embedding 模型，也没有调用外部 Embedding API。`_embed()` 使用特征哈希：

1. 提取英文单词、代码标识符、中文单字和双字组合；
2. 使用稳定的 BLAKE2 哈希把词映射到 512 维；
3. 对向量做 L2 归一化；
4. 查询和文档之间使用余弦相似度排序。

优点：

- 完全本地，不上传知识库；
- 不需要模型下载或额外密钥；
- 启动快，测试结果确定；
- 接口与真正的向量检索一致，方便以后替换。

限制：

- 它主要捕捉词和字符重合，不具备真正语义 Embedding 的同义词理解；
- 哈希冲突会带来少量噪声；
- 只适合当前小型知识库和教学版本。

因此，准确说法是“本地特征哈希向量检索”，不能在面试中把它夸大为深度语义检索。未来可以保持 `LocalDocumentIndex.search()` 接口不变，将 `_embed()` 替换为本地 Embedding 模型。

### 21.7 索引缓存和自动失效

索引保存在：

```text
.incident_cache/rag_index.json
```

程序对所有知识库文件的相对路径和内容计算 SHA-256 fingerprint：

- fingerprint 与缓存一致：直接加载向量，`cache_hit=true`；
- 新增、删除或修改文档：fingerprint 改变，自动重建索引；
- 缓存损坏：忽略旧缓存并重建。

`.incident_cache/` 已加入 `.gitignore`，因为索引可以由源文档重新生成，不应进入版本库。

### 21.8 retrieve_docs 的输入和输出

输入：

```json
{
  "query": "DeepSeek response_format 400错误",
  "top_k": 3
}
```

`top_k` 必须在 1 到 5 之间。输出片段包含：

```json
{
  "chunk_id": "44684939ba4aeca7",
  "source": "knowledge/troubleshooting.md",
  "section": "response_format 不可用",
  "line_start": 3,
  "content": "...",
  "score": 0.1686
}
```

`meta` 还会提供返回数量、索引片段总数、是否命中缓存以及检索方法。来源与行号让最终报告可以引用文档证据，而不是只返回无法追溯的文本。

### 21.9 三份知识库文档

- `database.md`：当前 checkpoint 状态、后续数据库持久化约定和敏感数据规则；
- `api.md`：模型配置、输出兼容模式与 Tool Calling 协议；
- `troubleshooting.md`：`response_format` 400、缺少 LangGraph、内存状态丢失等故障。

这些文件既是示例数据，也是项目当前真实约定。后续遇到并解决新问题时，应把可复用经验补充到相应文档，再让索引自动重建。

### 21.10 Git Tool 的设计原则

Git 工具采用“一个安全动作对应一个函数”，而不是危险的：

```python
run_git(command: str)
```

当前只允许固定的只读命令：

```text
git status --short --branch --untracked-files=all
git diff --no-ext-diff --unified=3 -- <受校验路径>
git log -N --no-decorate --date=iso-strict --pretty=<固定格式>
```

实现使用 `subprocess.run([...], shell=False)`：

- 不使用 shell 字符串拼接；
- `git_diff` 使用 `--` 分隔选项与路径，防止路径被解释成 Git 参数；
- 路径必须位于项目根目录；
- 禁止查看 `api.env` 等敏感文件；
- 命令超时为 8 秒；
- 输出最多 20,000 字符；
- `git_log.limit` 限制为 1 到 20。

没有提供 `reset`、`checkout`、`clean`、`commit`、`push` 等修改仓库的能力。

### 21.11 最终证据类型

`Evidence` 新增必填字段：

```python
source_type: Literal["code", "documentation", "git", "runtime", "unknown"]
```

最终显示示例：

```text
1. [documentation] knowledge/api.md:12 — 文档要求工具参数必须校验
2. [code] registry.py:48 — 参数在执行前通过 Pydantic 验证
3. [git] agent.py — 最近提交后控制流发生变化
```

这让使用者能区分“代码事实”“文档规范”和“版本历史线索”。

### 21.12 V4 测试

当前共有 26 项离线测试，其中新增 6 项：

- RAG 返回带来源、章节、行号和分数的片段；
- 第二次相同检索命中本地缓存；
- `git_status` 能只读获取状态；
- `git_log` 能限制提交数量；
- `git_diff` 拒绝敏感文件；
- Git 工具参数越界被 Pydantic 拒绝。

还实际验证了查询“DeepSeek response_format 400错误”时，第一条结果命中 `knowledge/troubleshooting.md` 的对应章节。

### 21.13 当前局限和下一步

- 当前检索是特征哈希，不是真正语义 Embedding；
- 没有文档相关性阈值或独立 reranker；
- 没有查询改写节点；
- Git Diff 当前只包含未暂存差异，不包含 staged diff；
- Git 输出还是大块文本，尚未解析成更细的结构；
- 还没有真实模型端到端评测。

下一步建议建立一组固定故障问题及标准答案，对“无 RAG”和“有 RAG”的根因准确率、引用正确率和工具调用次数进行对比。确认收益后，再替换真正的本地 Embedding，而不是只凭感觉增加复杂依赖。

### 21.14 V4 更新记录

- 新增 `retrieval.py` 与本地缓存索引；
- 新增 `knowledge_tools.py` 和 `retrieve_docs`；
- 新增 `git_tools.py` 与三个只读 Git 工具；
- 新增三份真实示例知识文档；
- 工具总数由 3 个增加到 7 个；
- 最终证据增加 `source_type`；
- `.incident_cache/` 加入 `.gitignore`；
- 离线测试由 20 个增加到 26 个。

## 22. 故障评测 Demo App

### 22.1 为什么需要 Demo App

最初的 `knowledge/` 是为了验证 RAG 管道而编写的 IncidentPilot 自身说明，内容少，也缺少真实业务代码与文档之间的对应关系。它可以证明“检索能运行”，但不能有力证明“RAG 能帮助定位故障”。

因此新增 `demo_app/`：一个完全本地、没有真实用户数据、专门用于 Agent 评测的小型 Python 系统。它包含可执行代码、真实对应的业务文档、稳定 Bug、日志和标准答案。

### 22.2 完整目录

```text
demo_app/
├── app/
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   ├── database.py
│   ├── pool.py
│   └── worker.py
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── database.md
│   ├── runbook.md
│   └── incidents/
│       ├── INC-001-missing-user-id.md
│       ├── INC-002-schema-mismatch.md
│       └── INC-003-connection-leak.md
├── logs/
│   ├── missing_user_id.log
│   ├── schema_mismatch.log
│   └── connection_leak.log
├── evals/
│   ├── missing_user_id.json
│   ├── schema_mismatch.json
│   └── connection_leak.json
├── run_case.py
└── README.md
```

### 22.3 三个故障案例

#### Case 1：缺少输入校验

```powershell
.venv\Scripts\python.exe -m demo_app.run_case missing_user_id
```

预期异常：

```text
KeyError: 'user_id'
```

真实根因是 API 层没有按照 `demo_app/docs/api.md` 验证必填字段，而 Service 使用 `payload["user_id"]`。这个案例测试代码工具和 API 文档 RAG 的组合。

#### Case 2：数据库迁移不一致

```powershell
.venv\Scripts\python.exe -m demo_app.run_case schema_mismatch
```

预期异常：

```text
sqlite3.OperationalError: table users has no column named user_id
```

数据库已经使用 `external_id`，Repository SQL 仍写入旧字段 `user_id`。这个案例要求 Agent 对照实际 Schema、迁移文档和 Repository 代码。

#### Case 3：连接泄漏

```powershell
.venv\Scripts\python.exe -m demo_app.run_case connection_leak
```

预期异常：

```text
RuntimeError: connection pool exhausted
```

Worker 在异常路径没有释放已经获取的连接，连续失败后连接池耗尽。这个案例测试调用链调查与 Runbook/历史事故检索。

### 22.4 为什么测试“期待失败”

`test_demo_app.py` 使用 `assertRaises` 检查三个异常。测试通过代表：

```text
故障夹具仍能按照设计稳定复现
```

不代表：

```text
Demo 业务代码已经正确
```

评测夹具中的 Bug 是测试数据的一部分。如果直接修复这些 Bug，对应评测就失去输入，需要保留 broken 与 fixed 两个版本或通过补丁动态构造故障。

### 22.5 RAG 最终检索哪些文件

`LocalDocumentIndex` 现在同时索引：

```text
knowledge/**/*.md
demo_app/docs/**/*.md
```

- `knowledge/`：IncidentPilot 自身的配置、持久化与排障知识；
- `demo_app/docs/`：Demo 业务系统的架构、API、数据库、Runbook 和历史事故。

它不会索引源代码、日志、标准答案、真实 `api.env` 或工作区中的 Word 文件。源代码由文件工具读取，日志由用户提供或文件工具读取，`evals/` 只能由后续评测器使用，不能作为 RAG 上下文泄露给 Agent。

为防止 Agent 直接读取标准答案，所有名为 `evals` 的目录都会被 `list_files` 和 `search_code` 忽略，`read_file` 与 `git_diff` 也会明确拒绝这些路径。`.incident_cache` 采用相同的内部目录保护。

### 22.6 标准答案的作用

每份 `evals/*.json` 包含：

- `case_id`；
- 用户问题；
- 预期异常；
- 根因必须命中的关键词；
- 应引用的代码文件；
- 与故障相关的文档。

后续评测器可以确定性检查 Agent 报告，而不需要立刻引入另一个 LLM 当裁判。

### 22.7 如何手动测试 Agent

1. 运行一个 Demo Case；
2. 复制完整 traceback；
3. 运行 `python main.py`；
4. 粘贴 traceback，并要求给出根因、代码证据和文档证据；
5. 对照相应 `evals/*.json` 检查结果。

示例问题：

```text
我运行 python -m demo_app.run_case schema_mismatch 后出现：
sqlite3.OperationalError: table users has no column named user_id

请结合代码、项目文档和 Git 信息调查根因，并给出证据。
```

### 22.8 当前验证结果

- 三个 Demo 命令均产生预期 traceback；
- 三个故障复现测试通过；
- RAG 可以检索 `demo_app/docs/`；
- `user_id → external_id` 查询能命中数据库迁移文档；
- 总离线测试达到 33 项，其中包含评测答案防泄漏测试；
- SQLite 测试连接会在 `finally` 中关闭，不产生资源警告；
- 尚未调用外部模型执行端到端评测。

### 22.9 下一步

下一阶段应实现正式的 `evals/runner.py`：自动读取 Case、运行 Agent、保存调查轨迹，并计算根因关键词命中率、证据文件命中率、引用有效性、模型调用次数、工具调用次数和运行时间。然后对比：

```text
只使用代码工具
代码工具 + RAG
代码工具 + RAG + Git
```

只有完成这组对照实验，才能用数据说明 RAG 和 Git Tool 是否真正提高了故障定位质量。

### 22.10 本次更新记录

- 新增可执行的 Demo App；
- 新增三个稳定故障案例；
- 新增 7 份业务与事故文档；
- 新增 3 份简化日志；
- 新增 3 份评测标准答案；
- RAG 数据源扩展到 `demo_app/docs/`；
- 新增 Demo、检索与评测隔离测试，总数达到 33 项。

### 文档更新记录

- 增加 LangGraph 的一句话和一分钟讲解版本；
- 增加从输入到输出的完整执行顺序；
- 补充 reducer、`tool_call_id`、报告验证和两层预算；
- 补充 checkpoint 的边界与常见面试追问。
