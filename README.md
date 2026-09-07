# IncidentPilot V2：保姆级项目手册

IncidentPilot 是一个用于排查 Python 项目故障的最小 Agent。

用户把错误日志和问题交给它以后，模型不会直接读取硬盘。它会选择本地工具来搜索代码、读取文件、收集证据；当证据足够时，再输出根因、证据和修复建议。

当前版本只负责**调查和提出建议**，不会运行目标项目，也不会修改代码。V2 已增加统一工具注册、严格参数校验、统一 JSON 工具结果、结构化最终报告和 `list_files`。

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
