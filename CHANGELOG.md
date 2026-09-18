# IncidentPilot 版本记录

本文件只记录版本演进、行为变化和迁移注意事项。当前版本的安装、使用、架构与完整原理统一写在 `README.md`。

## 文档维护约定

以后每次发布或完成一个版本，必须同步维护两个文件：

1. `README.md`：更新为新版本当前真实存在的能力、接口、命令、限制与测试结果，不保留已经失效的旧实现说明；
2. `CHANGELOG.md`：新增一个版本章节，记录新增、修改、修复、测试变化和兼容性影响。

如果只是修正文案且不改变程序行为，可以只更新文档；任何代码、配置、命令、数据结构或安全边界变化都必须同步更新两份文件。

---

## V14.5：Benchmark 第三批两个案例（2026-09-18）

- 保持 `graph.py`、Prompt、模型与工具预算、评分器、五个 development 案例及正式对照结果不变，新增 `pagination_off_by_one` 与 `config_env_rename` 两个 hidden 案例；Benchmark 版本升为 `v14.5`，当前共十个可执行场景、十三个 Evaluation 案例。
- `pagination_off_by_one` 复现公开 API 使用 1-based 页码、实现却直接以 `page * page_size` 计算切片起点而跳过第一页；`config_env_rename` 复现部署模板已使用 `HTTP_TIMEOUT_SECONDS`、应用仍读取旧 `REQUEST_TIMEOUT_SECONDS` 的启动失败。
- 每例均增加故障代码、模块/脚本复现、简化日志、业务契约、Evaluation，以及 reproduction/regression Harness Check。Harness 新增 `demo_pagination_off_by_one`、`pagination_page_number_contract`、`demo_config_env_rename`、`http_timeout_env_contract`，总数由 14 增至 18。
- 既有参数化测试矩阵扩展到六个新增案例：两种入口必须稳定失败，当前契约检查必须识别故障，临时副本应用最小参考修复后入口和契约检查必须共同通过；新增 Check/Eval 继续对 Agent 文件工具隔离。
- 三个相关测试模块共 30 项专项测试通过，完整离线测试保持 196 项并全部通过；`main.py doctor` 通过并确认 Harness 清单含 18 项。测试数量没有增加，因为本批继续扩展既有参数化矩阵。本阶段不调用真实模型，不产生 Token 费用，也不把新 hidden 案例写入冻结的 V13/V14.3 development 结果。

---

## V14.4：Benchmark 第二批两个案例（2026-09-18）

- 保持 `graph.py`、Prompt、模型与工具预算、报告校验器和五个 development 案例不变，新增 `timezone_mismatch` 与 `cache_key_version` 两个 hidden 案例；Benchmark 版本升为 `v14.4`，当前共八个可执行场景、十一个 Evaluation 案例。
- 每个案例都包含独立故障代码、模块/脚本复现入口、简化错误日志、正常业务契约、预登记 reproduction/regression Harness Check 和 Evaluation 标准。没有增加外部网络、任意命令或正式工作区写入能力。
- `timezone_mismatch` 用同一实际时间线上的 `Z` 与 `+08:00` 时间戳复现 SLA 误判，契约要求保留 offset 并按 elapsed time 比较；`cache_key_version` 用 v2 写入和旧格式读取复现写后读未命中，契约要求读写双方使用同一版本 Key。
- Harness 增加 `demo_timezone_mismatch`、`timezone_elapsed_contract`、`demo_cache_key_version`、`cache_key_version_contract`，总数由 10 增至 14；`demo_case` 允许集合扩展到八个固定目标，兼容 `run_demo_case` 仍只保留 V13 四案例。
- 扩展现有离线回归矩阵：两种启动方式必须稳定复现，故障版本的契约检查必须失败，临时副本应用最小参考修复后复现与契约检查必须共同通过；新增 Check/Eval 文件继续被 `read_file/search_code/list_files` 隔离，业务代码仍可调查。
- 三个相关测试模块共 30 项专项测试通过，完整离线测试保持 196 项并全部通过；`main.py doctor` 通过并确认 Harness 清单含 14 项。测试数量没有增加，因为本批直接扩展既有参数化回归矩阵。
- 冻结的 V13 和 V14.3 五案例正式结果均未修改；本阶段不调用真实模型，不生成新的通过率或成本结论。

---

## V14.3：假设更新空转控制（2026-09-18）

### 修复

- 初始假设成功保存后，`update_hypotheses` 会从下一轮 Tool Schema 隐藏；只有尚未建立假设或产生了新的成功 Observation 时才重新开放，强制调查在内部状态更新与外部取证之间推进。
- 新增执行层 `hypothesis_update_not_allowed` 保护。即使 OpenAI-compatible 服务返回未声明的假设工具，没有新证据时也不能覆盖状态。
- 新增连续失败计数：一次无效假设更新仍允许模型纠正，连续两次无效或越权更新会停止工具调查并根据现有证据总结，防止内部格式修复耗尽全部模型预算。
- `next_action` 校验从“每个 unverified/supported 假设都必须提供”改为“完整开放集合至少有一个可执行动作”。supported 候选可以暂时没有动作，只要另一开放候选明确给出下一项高信息价值调查。
- Prompt 同步说明假设工具的开放条件与集合级动作约束；未放宽 Observation 引用、状态证据、报告置信度或 Provenance 校验。

### 验证与范围

- 新增四项回归测试，覆盖集合级 `next_action`、Schema 动态隐藏/重开、未声明重复更新的执行层拒绝，以及两次无效更新后的有界收尾；完整离线测试增至 177 项并全部通过。
- 本阶段没有修改 Evaluation 标准、Benchmark 数据、上下文压缩、文件读取、语义重复检测、调查预算或 Runtime 安全边界。
- 唯一一次真实验收 `schema_mismatch + full` 由 V13 失败变为 1/1 通过：根因/代码/引用/Evidence/Claim 均为 100%，模型调用 10→5、工具调用 12→8、Token 56,844→22,005、耗时 50.15→22.28 秒，格式修复 1→0，fallback 维持 0；第 4 步 confirmed 后提前总结，未再发生连续四轮假设更新。
- 该验收的文档覆盖仍为 0%，Observation 利用率由 83% 降至 60%；而且它只是单案例单次样本，不是正式五案例 V14 对照，不能外推为总体性能结论。

### 第二项优化：定向文件读取

- `read_file` 新增 nullable 的 `start_line/end_line`。行号从 1 开始且包含两端，返回内容继续使用原始文件行号；只提供起始行时默认读取最多 30 行，不传行号时保留旧整文件行为。
- 定向窗口硬限制为 30 行；反向范围、过大窗口、非正整数和超过文件总行数的起始行都会返回结构化失败，不通过扩大读取范围掩盖定位问题。20,000 字符总上限继续生效。
- Prompt 要求已有搜索命中行时优先读取附近窄窗口，避免为确认一个命中位置反复读取整个长文件。
- 注册器在严格模式递归规范化 JSON Schema：每个对象的 `required` 覆盖全部 `properties`、移除 `default`、保留 `null` 联合类型；非严格 Schema 和本地 Pydantic 默认值不变。这保证新增逻辑可选字段兼容 DeepSeek/OpenAI 严格工具格式。
- 新增五项离线回归测试，覆盖定向范围、原始行号、反向/超大范围、起始行默认窗口、严格 nullable Schema 和非严格兼容；完整测试增至 182 项并全部通过。
- 在干净提交 `4c2200e` 上唯一一次真实验收 `missing_user_id + full` 机器评分为 1/1：严格 Schema 没有 400，模型执行三次不超过 30 行的定向读取；模型调用 10→5、工具调用 13→8、Token 61,085→23,705、耗时 60.58→20.76 秒，格式修复 1→0。
- 人工审计判定该报告只完成直接故障链而非完整系统根因：未读取 `api.py` 与 `api.md`，代码覆盖 50%、文档覆盖 0%，报告自身也声明 API 校验尚未验证；Observation 利用率 83%→50%。机器评分仍通过，暴露出当前通过阈值允许半数必需代码文件和零文档覆盖，不能把 1/1 外推为完整诊断质量提升。
- 原始报告 `.incident_reports/eval-20260918-192237.json` 的 SHA-256 为 `c5cd3d966dae102ae6fe05d1915531ca8ce00a1f5915a652de8491ab2960a2ff`，元数据记录 `repository_commit=4c2200e...`、`working_tree_dirty=false`。

### 第三项优化：关键证据压缩

- 成功的定向 `read_file` Observation 改用紧凑的 `path` 与 `行号: 内容` 摘要，不再直接截取原始工具 JSON 的前 1,000 字符；最多 4,000 字符的总预算会按窗口行数分配，保证末端行仍出现在摘要中。
- 上下文压缩对定向文件窗口保留最多 4,000 字符，避免 Observation 已保留的末端证据又被统一 700 字符上限截掉。普通工具继续使用 Observation 1,000 字符、模型上下文 700 字符的既有边界。
- 完整工具结果的 SHA-256、精确文件来源、Evidence 白名单和 Checkpoint 消息不变；没有放宽引用验证、评分标准、调查预算或文件访问隔离。
- 新增三项回归测试，覆盖定向窗口末行在 Observation 中可见、经过上下文压缩后仍可见，以及普通 Observation 继续限制为 700 字符；完整离线测试增至 185 项。
- 在干净提交 `5a88208` 上只运行一次 `missing_user_id + full`：定向 `run_case.py:20–49` 摘要保留末端及第 35–36 行关键调用，模型随后读取 `api.py`、`service.py`、`repository.py`，最终完整说明非法 payload 经无校验 API 进入 Service 并由 `payload["user_id"]` 触发 `KeyError`。
- 机器评分 1/1，根因/代码/引用/Evidence/Claim 均为 100%，Provenance 违规、格式修复和 fallback 均为 0，两个 confirmed 假设触发早停；与 V13 基线相比模型调用 10→8、工具调用 13→13、Token 61,085→44,612、耗时 60.58→47.67 秒，Observation 利用率 83%→75%。
- 文档覆盖仍为 0%，两条成功 Observation 未被最终报告引用；相较第二项的单次验收，诊断更完整但模型、工具与 Token 使用回升。因此该样本只验收证据保留与完整根因链路，不构成总体成本提升结论。
- 原始报告 `.incident_reports/eval-20260918-195735.json` 的 SHA-256 为 `f1567eaf6cbf2e1a9f8750ecb29a111abc7437985c0d3f1f70a62b2b3f2175dd`，元数据记录 `repository_commit=5a88208...`、`working_tree_dirty=false`。

### 第四项优化：文件范围语义去重

- 定向 `read_file` 在执行前会汇总同一规范化路径的成功 Observation 来源区间；新窗口由一个旧窗口或多个相邻窗口的并集完整覆盖时，不再访问文件。
- 被拦截调用返回 `duplicate_read_range`、`repeated=true` 和 `covered_by_observation_ids`，模型可以直接复用旧证据。该调用继续计入既有重复指标，并沿用第一次允许纠正、累计第二次才强制总结的控制策略。
- 部分重叠但确实包含新行的请求继续执行；失败、越界、预算拦截和重复 Observation 不建立覆盖范围。整文件请求的未知末行不会被不完整窗口推测，其他工具继续按规范化参数精确去重。
- Prompt 同步要求读取前检查压缩记忆中的成功范围；没有修改工具 Profile、文件隔离、Evidence 校验、评分标准或调查预算。
- 新增四项回归测试，覆盖多 Observation 联合覆盖、被包含窗口拦截、部分重叠新增行放行和失败范围不污染记录；完整离线测试增至 189 项并全部通过。
- 在干净提交 `2cc5f0a` 上只运行一次 `missing_user_id + full`，机器评分 1/1；根因/代码/引用/Evidence/Claim 均为 100%，Provenance 违规、格式修复和 fallback 均为 0。模型调用 9 次、工具调用 16 次、Token 42,336、耗时 42.28 秒，Observation 利用率 66.67%。
- 报告完整覆盖缺失字段经 API 透传后在 Service 触发 `KeyError` 的链路，但只有 supported 假设、没有早停，文档覆盖仍为 0%，三条成功 Observation 未引用；另有三次超大范围读取失败和一次 Profile 禁止工具调用。
- 本次唯一重复是精确相同的 `search_code("user_id")`，没有请求被旧窗口完整覆盖的 `read_file`，所以真实运行只证明无回归，不证明新语义分支被触发。`duplicate_read_range` 的确定性验收来自四项离线执行层回归，不能混淆两种结论。
- 原始报告 `.incident_reports/eval-20260918-201809.json` 的 SHA-256 为 `a3050fb4c5bf0e672990b1b15de61b6849822522ed5fecd2c4fb7f0980b477c0`，元数据记录 `repository_commit=2cc5f0a...`、`working_tree_dirty=false`。

### 第五项优化：最后证据归类与上游根因追踪

- 新增独立的 `classify_final_evidence` 节点。调查步骤、证据充分度或调查阶段模型额度触发停止时，只要最后一批成功 Observation 尚未归类且硬预算仍有三次请求，系统会先执行一次只暴露 `update_hypotheses` 的受限归类。
- 受限归类计入总模型调用和 Token，但不增加调查 `step_count`；无论归类成功或失败，下一节点都立即总结，不再返回普通调查。`final_classification_attempted` 保证整次运行最多进入一次。
- 执行层新增 `final_classification_only` 保护。即使兼容服务返回未在 Schema 声明的文件、RAG、Git 或 Runtime 工具，也只生成失败 Observation，不实际执行。
- 调整模型预算预留：没有假设时继续为总结与格式修复预留两次请求；已有假设时为最后归类、总结与格式修复预留三次请求。剩余预算不足时跳过归类，优先保证可验证的最终报告，不提高 `MAX_MODEL_CALLS`。
- 系统提示明确区分异常抛出行这一 failure site 与系统根因；定位异常行后必须继续检查至少一个上游调用方及相关接口或业务契约。遇到 `KeyError`、缺字段或非法输入时优先核对 API/入口校验，不能只把下游下标访问改成 `.get()`。
- `RunMetrics` 新增兼容默认值为 0 的 `final_classification_count`，记录受限归类是否实际发生；旧结果文件仍可读取。
- 新增五项 Graph 回归测试，覆盖待归类证据与三次预算门、单次归类路由、failure site 提示、最后成功 Observation 的归类，以及兼容服务越权外部工具的执行层拒绝。完整离线测试增至 194 项并全部通过。
- 没有修改 Evaluation 标准、Benchmark 数据、工具 Profile、文件隔离、Evidence/Claim 来源验证、默认模型/工具预算或 Runtime 安全边界。
- 在干净提交 `f43f30d` 上只运行一次 `missing_user_id + full`，机器评分 1/1；根因、必需代码、文档、引用、Evidence 与 Claim 均为 100%，Provenance 违规、重复调用和 fallback 均为 0。模型读取缺字段调用、API、Service、Repository 和 API 契约，明确区分 Service failure site 与 API 入口校验根因，形成 3 个 confirmed 假设并提前结束；模型调用 9 次、工具调用 13 次、Token 51,686、耗时 57.30 秒、Observation 利用率 77.78%，格式修复 1 次。
- 本次 `final_classification_count=0`，因为最后证据已在第 7 个调查步骤正常归类并触发早停；真实运行验证了上游根因追踪与新指标兼容性，但没有触发预算末尾受限归类分支。该分支的行为、安全拒绝和预算边界仍由离线回归确定性验收，不能把本次 1/1 误写成真实触发证明。原始报告 `.incident_reports/eval-20260918-212806.json` 的 SHA-256 为 `f6a6ecc35a6e0880dbc31826f2c29f6081ac225b1265b2cfc1b8ba80d1eaa23b`。

### 正式 development 对照

- 在干净提交 `234a2a4` 上以与 V13 相同的五个 development 案例、`full` Profile、每例一次和相同硬预算运行正式 V14.3 对照；没有补跑失败案例。
- 通过率由 V13 的 1/5（20%）提升到 3/5（60%），提高 40 个百分点。平均根因覆盖 40%→93.33%、代码覆盖 50%→100%、文档覆盖 20%→80%、引用/Evidence/Claim 覆盖均为 60%→100%，Observation 利用率 61.07%→70.62%。
- 平均模型调用 9.8→8.6（下降 12.24%），平均 Token 57,336.6→52,684.2（下降 8.11%），格式修复 4→2，fallback 2→1，未引用成功 Observation 17→13。平均工具调用 13.6→14.0（增加 2.94%），总耗时 262.84→321.25 秒（增加 22.22%），所以不宣称所有性能指标都改善。
- `connection_leak` 与 `retry_non_idempotent` 各真实触发一次预算末尾受限归类；前者通过，后者虽然形成两个 confirmed 假设并找到正确根因，但最终 Evidence 来源越界且格式修复仍失败，按 `invalid_synthesis` 保持失败。
- `async_missing_await` 的报告正确识别漏写 `await`、coroutine object 和异步契约，但未命中确定性标准中的中文关键词“协程”，按原标准保持失败；没有事后放宽关键词或评分阈值。
- 五个案例最终引用均来自允许的业务代码或索引文档，Provenance 违规总数为 0。逐例审计和差值保存在 `demo_app/evals/results/v14.3-development.json`；原始报告 `.incident_reports/baselines/v14.3-development/v14.1-development-20260918-215356.json` 的 SHA-256 为 `3df3d595413c8646d6dfb1493c80e4412076b6c3806e842262708df456c3d64e`。
- 每个案例仅运行一次，以上是固定模型、固定五案例的小样本对照，不代表方差、稳定通过率或生产性能。

### 正式对照后的 Evidence 合约加固

- `retry_non_idempotent` 的失败显示，模型会把零命中 `search_code` 的 Observation ID 与另一个 RAG Observation 的文件和行号拼接。报告验证器正确拒绝了结果，但旧的嵌套来源提示仍给模型留下了错配空间。
- 最终总结与格式修复的来源白名单改为逐来源扁平展开；每个对象直接包含 `observation_id/source_type/file/line_start/line_end/commit_hash/runtime_id`。模型必须完整复制同一对象，不能跨对象拼接字段。
- 成功但没有任何来源的 Observation 不再进入 Evidence 白名单，只能保留为推理线索；格式修复明确要求把不匹配的 Evidence 整项替换或删除，并移除未被任何 Claim 使用的 Evidence。
- Provenance Validator、Evidence/Claim Schema、Evaluation 标准、模型调用次数和格式修复次数上限均未改变；没有针对 Case ID 写规则，也没有自动把无效来源映射成合法来源。
- 新增两项 Graph 回归测试，覆盖无来源 Observation 的白名单排除，以及文件与 Observation 错配后使用扁平精确来源完成一次修复。完整离线测试增至 196 项并全部通过。
- 在干净提交 `38494ed` 上只复验一次 `retry_non_idempotent + full`，没有补跑。机器评分 1/1；根因、必需代码、引用、Evidence 与 Claim 覆盖均为 100%，Provenance 违规和 fallback 均为 0。模型调用 9 次、工具调用 15 次（唯一外部调用 12 次）、Token 55,142、耗时 57.12 秒、Observation 利用率 66.67%。
- 报告正确给出“首次支付可能已成功、超时后因缺少幂等键再次扣款”的根因，并把 `run_case.py:58` 作为检测/失败位置。首次报告只有一项未被 Claim 使用的 `E2`，一次格式修复将其删除；正式对照中的 Observation ID 与 RAG 文件/行号错配没有重现。
- 文档覆盖为 0%，因为本次 RAG 没有返回支付契约正文；报告保留契约未确认的不确定性，Fixture 读取也被既有隔离阻止。原始报告 `.incident_reports/eval-20260918-232704.json` 的 SHA-256 为 `bd3ba81c0615f299c60be8d526d29ed36ca15719c49c9cf25cbc0873e5c59cff`。
- 该结果是修复后的单案例验收，不属于已冻结的五案例正式 V14.3 对照，未覆盖 `demo_app/evals/results/v14.3-development.json` 中的 3/5 结果。

---

## V14.1：Benchmark 首批两个案例（2026-09-18）

- 以 V13 `8c804fb` 为基点，修改前完整 155 项离线测试与 doctor 通过。
- 新增 `async_missing_await`、`retry_non_idempotent`，每例包含故障代码、模块/脚本复现入口、简化日志、业务文档、Evaluation 标准。
- Harness 新增两个 reproduction、两个 regression Check，共十个；复现检查预期非零退出，契约检查在当前故障代码上预期失败。默认测试验证故障与临时副本参考修复的两面行为。
- 补上 read_file/search_code/list_files 对 checks 目录的隔离；既有 fixtures/evals 隔离继续保留。正式对照需统一此隔离边界。
- 移除三份直接写出旧案例根因的事故文档；原评测改为引用 API、数据库和 Runbook 契约，RAG 指纹会自动重建。
- 新增 `_benchmark_manifest.json`，冻结五个 development、一个 hidden、两个 challenge 和一个 runtime 案例。连接泄漏的两个变体不再冒充未见故障泛化。
- `run_evals.py` 默认只选 development；跨集合案例会被拒绝。正式 baseline 要求干净工作区，报告写入独立目录且禁止覆盖，并记录提交、数据摘要、模型配置和预算元数据。
- 首次单案例烟雾运行发现 `test_graph.py`、Harness/Runtime 实现仍可被搜索，报告引用测试答案后获得 1/1；该结果已隔离并标记 invalid，不计入基线。
- 文件工具现在统一隐藏所有 `test_*.py` 及 Harness、Runtime、doctor、Benchmark 实现；同时清理业务代码中的答案式 BUG 注释和故障提示性 docstring。
- 新增十八项离线测试，总计 173 项。测试不调用真实模型，不访问支付网络，不修改正式故障代码。
- 保持 graph.py、Prompt、模型/工具调用预算、上下文压缩、假设协议及评分器原样；兼容 run_demo_case 仍为 V13 的四个案例，新增案例使用 run_check。
- 隔离修复提交 `3c1b4b8` 的 `missing_user_id + full` 来源审计通过，形成首个有效 V13 单案例基线：0/1，根因 33%、代码 50%、文档 0%、引用/Evidence/Claim 100%，10 次模型调用、13 次工具调用、61,085 Token、60.58 秒、格式修复 1、fallback 0。失败表现为只定位 Service 抛错点，没有读取 API 与契约，并在后半段连续更新假设。
- 完成五个 development 案例的 V13 单次基线并通过来源审计：1/5（20%），平均根因 40%、代码 50%、文档 20%、引用/Evidence/Claim 60%、Observation 利用率 61%；平均 9.8 次模型调用、13.6 次工具调用、57,337 Token，总 Token 286,683、总耗时 262.84 秒；格式修复 4/5，fallback 2/5，Provenance 违规与重复调用均为 0。
- 新增 `demo_app/evals/results/v13-v14.1-development.json`，保存逐例指标、原始报告 SHA-256、实验配置、来源审计和适用限制；原始含调查内容的报告继续只保存在被隔离且 Git 忽略的 `.incident_reports/`。
- 当前尚无 V14 提升结论；后续优化必须使用相同五案例、Profile、预算和单次运行口径进行对照。

## V13：Patch Sandbox Verification（隔离补丁验证）

### 新增

- CLI 新增 `main.py new --verify-patch`；该参数自动启用 Patch Proposal，并在提案通过本地结构校验后进入独立验证审批。原 `--with-patch` 继续只生成只读提案。
- 新增 `patch_verification.py`：重新校验 proposal ID 与当前文件上下文，把项目安全子集复制到系统临时目录，在副本中运行基线、应用 unified diff、运行补丁后检查并清理目录。
- 新增结构化 `PatchCheckRun` 与 `PatchVerificationResult`，保存每个检查的阶段、用途、退出码、成功条件、测试计数、失败项、输出摘要、超时、错误与耗时。
- Harness 检查新增 `purpose=reproduction|regression` 和 `covers_files`。系统自动合并模型建议项、所有覆盖修改文件的检查和全局回归检查；修改文件没有任何覆盖声明时拒绝验证。
- 新增 `api_missing_fields_contract`，验证缺少 `user_id` 或 `email` 时 API 返回 400 且不调用 Service，完整 payload 仍返回 201。
- 持久化会话新增 `waiting_for_patch_approval`，终端会在任何临时写入和检查执行前显示本次 proposal 与实际检查 ID。

### 判定语义

- `reproduction` 检查在补丁前必须命中预期故障；补丁后必须以 0 退出且不再命中旧故障退出码。
- `regression` 检查只以补丁后是否满足清单中的预期退出码判定。基线结果仍会记录，便于比较。
- `validated` 只表示候选 diff 的结构、范围、Claim/Evidence 与当前上下文合法；`verified` 才表示本次临时副本中的基线、应用和补丁后检查全部满足规则。
- 把 `KeyError` 替换成 `ValueError` 但没有落实“返回 HTTP 400 且不调用 Service”的补丁，会被契约检查判为 `failed`。

### 安全与成本

- 正式工作区永不应用候选补丁；系统在验证前后比较目标文件 SHA-256，并在结果中记录 `workspace_unchanged` 与 `sandbox_cleaned`。
- 临时复制排除 `.git`、`.venv`、API 密钥、缓存、评测报告、SQLite 状态和所有符号链接。候选 diff 仍不能修改测试、Harness、Evaluation、配置、Fixture 或内部基础设施。
- 补丁审批与费用审批、Runtime 工具审批、Memory 审批彼此独立。拒绝或取消时不创建临时目录、不启动子进程。
- 验证只运行项目所有者预登记的固定 Runner，使用 `shell=False`、固定工作目录、最小环境和全局超时；模型不能提供命令、参数或环境变量。
- `--verify-patch` 相对 `--with-patch` 不增加模型调用或 Token；新增成本仅为本地文件复制和基线/补丁后 Harness 时间。
- 当前隔离是临时工作区隔离，不是容器或操作系统安全沙箱；已登记检查必须来自可信项目代码。

### 兼容性与验证

- 普通诊断、Evaluation、`--with-patch` 和旧 Python API 默认行为不变；只有显式 `verify_patch_proposal=True` 或 `--verify-patch` 才进入新路径。
- `HarnessCheck` 新字段带兼容默认值，旧清单仍可加载；现有 Demo 项已补充明确的复现语义和文件覆盖声明。
- 新增隔离应用、正确补丁通过、错误异常替换被拒绝、正式工作区保护、Graph interrupt/resume、CLI 参数和会话状态测试。
- 155 项离线测试与 `doctor` 全部通过；未调用真实模型 API，未产生 Token 费用。

---

## V12.1.1：最终报告落地与补丁跳过原因修复

### 修复

- 为强制总结和最后一次格式修复请求加入由 `IncidentReport.model_json_schema()` 实时生成的严格 Schema，明确禁止 `gaps` 等额外字段，并强调 `suggested_fixes` 必须是字符串数组。
- 每次最终输出同时提供本次成功 Observation 及其真实来源白名单；模型只能复制其中的 `observation_id`、文件、行号、Commit 或 Runtime ID，减少修复阶段编造和错配 Evidence。
- 明确区分 Evidence ID 与 Observation ID：模型创建 `E1/E2` 后，Claim 只能引用最终 Evidence 数组中确实存在的 ID，不能引用被省略的 Evidence。
- 当报告经过两次尝试仍只能生成 `invalid_synthesis` 降级报告时，显式记录 Patch Proposal 因前置验证失败而跳过，不再显示空白的“补丁提案未生成”。

### 安全与成本

- 降级报告即使具有 high 置信度，也不能进入补丁节点；会明确说明安全跳过原因。
- 没有增加新的模型调用或格式重试。Schema 与来源白名单只附加到本来就会发生的总结/修复请求，目标是减少昂贵的修复调用。
- Pydantic、Hypothesis Readiness、Provenance 与 Patch 校验规则保持严格，没有把失败的模型报告自动标记为正常完成。

### 文档与验证

- README 已同步为 V12.1.1，解释报告 Schema、Observation 白名单以及降级报告为什么不能生成补丁。
- 新增报告契约测试，并扩展总结、修复和降级路径的 Graph 测试。
- 147 项离线测试全部通过；未调用真实模型 API，未产生 Token 费用。

---

## V12.1：DeepSeek Patch Schema 兼容性修复

### 修复

- 修复只支持 `response_format={"type":"json_object"}` 的模型虽然返回合法 JSON，却自行生成 `type`、`patch_id`、`objective`、`reasoning`、`status` 等字段，导致严格 `PatchProposalDraft` 校验失败的问题。
- 补丁请求现在直接携带由 `PatchProposalDraft.model_json_schema()` 实时生成的紧凑 JSON Schema、精确六字段示例和禁止字段列表；提示与 Pydantic 模型共用同一来源，避免手工复制后漂移。
- 补丁节点现在提供当前 `harness.json` 中真实登记的检查 ID 与公开说明。模型无需猜测 `verification_check_ids`，也看不到 Runner target 或命令。
- Harness 清单或输出契约无法读取时，在调用模型前返回本地错误，不产生无效补丁请求。

### 安全、成本与兼容性

- 没有接受或映射模型自创字段，也没有放宽 `extra="forbid"`、Claim、Evidence、路径、hunk、改动范围和 Harness ID 校验。
- `proposal_id`、`status` 与 `validation_errors` 仍只能由本地系统生成；模型不能自行声明补丁通过。
- 没有增加格式修复重试，显式请求补丁仍最多增加一次无工具模型调用。
- 原生支持 `json_schema` 的服务商继续使用 API Schema；提示内契约作为跨服务商的共同约束，不改变普通诊断和 Evaluation。

### 文档与验证

- README 已同步为 V12.1，新增 `json_schema` 与 `json_object` 的能力差异、兼容策略和可信边界说明。
- 新增测试确保提示包含全部模型字段、明确禁止系统字段并提供真实 Harness ID；Graph 集成测试验证最终补丁请求确实携带这些内容。
- 146 项离线测试全部通过；未调用真实模型 API，未产生 Token 费用。

---

## V12：Read-only Patch Proposal（只读补丁提案）

### 新增

- 新增 `PatchProposalDraft` 与 `PatchProposal` 结构化模型。模型只负责声明关联 Claim、修改文件、unified diff、修复理由、风险和建议运行的 Harness 检查；提案 ID、状态与校验错误由本地系统生成。
- 新增 `patching.py`，从已经通过来源验证的代码 Evidence 构造最小源码上下文，解析模型草稿，并对候选 diff 做确定性校验。
- LangGraph 新增可选 `propose_patch` 节点。只有最终诊断报告有效且调用方显式请求时才会进入该节点。
- CLI 新增 `main.py new --with-patch`；Python API 新增 `generate_patch_proposal=True`。终端和 `AgentRunResult` 均可返回提案或拒绝原因。
- 运行指标新增是否请求、是否生成及是否通过本地校验三个 Patch 字段。

### 校验与安全边界

- Patch 必须绑定报告中真实存在且已有 Evidence 的 Claim；修改文件必须已经出现在本次代码 Evidence 中。
- 只允许最多 3 个现有 `.py` 文件和合计 120 行增删，拒绝创建、删除、重命名、二进制补丁、路径越界和不完整 unified diff。
- 本地逐个 hunk 核对旧/新行数，并要求旧内容与当前磁盘文件精确匹配，防止把过期上下文应用到新版本源码。
- 禁止修改测试、Harness、Evaluation、配置、Fixture、缓存和状态数据；建议验证的 Harness ID 必须已经登记。
- V12 没有文件写入、`git apply`、补丁后执行或批准应用入口。`validated` 只表示候选 diff 结构、范围和当前上下文有效，不表示业务语义正确或测试已经通过。

### 成本与兼容性

- 普通 CLI、现有 Evaluation 和 `run_agent()` 默认不生成补丁，模型调用数与 V11 保持一致。
- 只有显式 opt-in 才增加最多一次无工具模型调用；低置信度、缺少 Claim/Evidence 或没有代码 Evidence 时由本地规则直接跳过，不消耗补丁生成调用。
- 新增状态和结果字段均提供默认值，旧 SQLite Checkpoint、已保存结果和现有 Python 调用方式继续兼容。
- 格式或 hunk 校验失败时保存 `rejected` 结果，不进行第二次模型格式修复，避免不可控重试成本。

### 文档与验证

- README 已同步为 V12 当前实现，补充命令、Graph 路径、Patch Schema、校验规则、成本模型、安全边界、限制和面试讲法。
- 新增草稿解析、合法提案、文件未取证、未知 Claim/Harness、受保护文件、过期上下文、Graph opt-in 和原文件字节不变测试。
- 145 项离线测试全部通过；未调用真实模型 API，未产生 Token 费用。

---

## V11：Safe Test Harness（安全测试执行框架）

### 新增

- 新增 `harness.json`，由项目所有者预登记允许执行的检查。每项固定声明 ID、Runner、target、说明、超时和预期退出码。
- 新增 `harness.py` 与 `list_checks()`、`run_check(check_id)`：模型只能发现并选择检查 ID，不能传入命令、参数、路径、工作目录或环境变量。
- 支持 `demo_case`、标准库 `unittest` 和可选 `pytest` 三种固定 Runner；默认清单包含四个故障复现和一个公开 Smoke Test，不新增必装依赖。
- 新增结构化测试结果：实际/预期退出码、`expectation_met`、通过/失败数量、失败测试名、异常类型、异常消息、traceback 帧、截断输出和 Runtime ID。
- `doctor` 新增 Harness 清单检查；即使第三方依赖缺失，也会用标准库执行基础 JSON、版本和非空检查。

### 控制流与证据

- `run_check` 接入现有 LangGraph `runtime_review`：执行前使用原生 interrupt 请求单次人工批准，拒绝时不启动进程，批准后从原 Checkpoint 恢复。
- `run_check` 与兼容工具 `run_demo_case` 共用 Runtime 配置开关、`full_runtime` Profile、调用预算、全局超时、运行指标、Runtime Provenance 和 SQLite 幂等账本。
- 来源提取器接受 `run_check` 生成的系统 `run_id`；报告中的 Runtime Evidence 仍必须与真实成功 Observation 精确绑定。
- Agent 提示词优先要求先 `list_checks` 再 `run_check`；旧 `run_demo_case` 保留，现有调用方和 V9/V10 Evaluation 不需要迁移。

### 安全与一致性

- 清单使用严格 Pydantic Schema，拒绝未知字段、重复 ID、非法退出码、过长超时和不受支持的 Runner。
- Agent 文件工具隐藏 `harness.json`；`unittest` 只接受无参数的点分模块名；`pytest` 只接受仓库内现有目标，拒绝越界、通配符、敏感目录、评测目录、外部系统夹具和 Harness 内部测试。
- 命令完全由系统使用当前 Python 构造，固定工作目录、`shell=False` 和最小环境；API Key 不进入测试进程。
- 实际超时取清单值和全局 `RUNTIME_TIMEOUT_SECONDS` 的较小值，项目清单不能放宽管理员设置的硬上限。
- 清单原文与单项定义分别计算 SHA-256；幂等键包含检查定义哈希，配置变化后不会错误重放旧检查结果。
- 非零退出码不再直接等同失败：故障复现可把 1 声明为预期，普通测试则通常要求 0，以 `expectation_met` 表达检查语义。

### 文档与验证

- README 已同步为 V11 当前实现，新增 Harness 配置、完整安全边界、执行原理、无 Token 测试方式、面试讲法和 V12–V14 规划。
- 新增 Harness 参数隔离、未知 ID、清单校验、固定 argv、最小环境、双重超时、测试结果解析、幂等重放、真实故障复现和 Graph 审批恢复测试。
- 135 项离线测试全部通过；未调用真实模型 API，未产生 Token 费用。

---

## V10.2 Stable：交互收口、启动自检与可重复基线

### 交互稳定性

- `main.py new` 遇到 LangGraph interrupt 后不再默认退出。Checkpoint 仍先同步写盘，但 CLI 会当场显示审批请求、读取选择并在内部调用 `Command(resume=...)`。
- 恢复后如果再次遇到 Runtime 或费用审批，同一个命令会继续处理，不要求用户反复复制调查 ID。
- `Ctrl+C` 或 EOF 只结束当前 CLI，不自动批准、取消或删除调查；终端会给出精确 `resume` 命令，稍后可以从原节点继续。
- `main.py resume` 同样支持连续审批自动恢复；新增 `main.py new --detach`，保留“遇到审批就保存退出”的异步使用方式。
- CLI 显示的后续命令统一使用 `.\.venv` 虚拟环境 Python，减少激活脚本和解释器路径混淆。

### 启动自检与依赖

- 新增 `doctor.py` 和 `main.py doctor`，在本机检查 Python 版本、五个直接依赖、`api.env` 格式和 SQLite 状态库；独立 `doctor.py` 只有标准库依赖，即使 LangGraph 尚未安装也能报告问题。
- `doctor` 不创建模型客户端、不发起网络请求、不输出 API Key；成功返回退出码 0，任一检查失败返回 1。
- 新增 `requirements.lock`，记录本次完整测试使用的五个直接依赖精确版本；原 `requirements.txt` 继续保留兼容范围供日常升级。
- V10 SQLite 数据库启动时自动迁移 Memory 召回字段，已有调查无需删除或重建。

### 边界与兼容性

- Runtime 仍必须在执行前得到明确授权；V10.2 只隐藏手工 resume 操作，没有绕过 HITL、Profile、开关、预算或幂等账本。
- Memory 审批仍是非阻塞的事后管理，不会为了沉淀历史经验中断当前诊断。
- `run_agent()`、无参数连续交互模式、Evaluation、工具 Schema 和报告格式保持兼容，没有新增 Agent 文件或命令权限。

### 验证

- 新增同进程审批恢复、中断后保留等待状态、`--detach`/`doctor` 命令、本地自检密钥隐藏和 V10 数据库迁移测试。
- 124 项离线测试全部通过；使用假模型和临时 SQLite，未调用真实模型 API，未产生 Token 费用。

---

## V10.1：Audited Incident Memory（可审批事故记忆）

### 新增

- 新增 `IncidentMemory`、`IncidentMemoryMatch` 和 `MemoryStatus` 数据模型，长期记录异常类型、关键符号、来源文件、根因、解决建议、源调查 ID 与审批时间。
- 新增 `memory.py`，负责合格候选提取、可解释词法相似度、确定性排序和安全上下文格式化。
- SQLite 新增 `incident_memories` 表和状态索引；`incident_sessions` 自动迁移 `recalled_memory_ids_json` 字段，旧 V10 数据库可直接打开。
- `main.py` 新增 `memory list/search/approve/reject/forget` 命令；所有记忆管理与检索都在本地完成，不调用模型。
- 持久化 `new` 调查会召回最多 3 条相似 approved Memory，并把实际 Memory ID 写入会话索引，把召回数量写入 `RunMetrics` 和实验聚合。

### 记忆生命周期

- 只有 `completed`、medium/high 置信度、同时具有 Claim 和 Evidence，且所有 Claim 引用都能落到真实 Evidence 的报告，才生成 `pending` 候选。
- 候选默认不能影响后续调查；只有用户显式 `approve` 后才进入召回池。`reject` 保留审计记录，`forget` 精确永久删除指定记录。
- 同一源调查最多生成一条候选，重复完成或重复持久化不会造成重复记忆。
- 召回使用异常类型、标识符、英文词和中文二元词组做本地排序，并对异常类型和关键符号精确匹配加权；没有 Embedding、向量数据库或额外 Token 成本。

### 安全

- 召回内容以“历史候选假设”注入 System 上下文，明确声明不是本次 Observation，不能作为 Claim/Evidence 或单独提高置信度。
- `Evidence.source_type` 不接受 `memory`，历史结论必须通过当前代码、RAG、Git 或 Runtime 工具重新验证后才能进入最终证据链。
- pending 和 rejected 记录完全不参与召回，降低未经人工筛选的错误报告造成记忆污染的风险。
- 记忆数据保存在已隔离的 `.incident_state/incident_pilot.sqlite3`，不会被 Agent 文件工具读取或提交到 Git。

### 兼容性

- 原 `run_agent()` 和无参数 `main.py` 路径继续使用内存 Checkpoint，不读取或写入长期记忆，已有调用方行为不变。
- 仅 `main.py new/resume` 持久化路径生成和召回 Memory；V10 的现有 SQLite 文件由启动迁移自动补字段，无需手工重建。
- 没有新增 Python 依赖，也没有修改 `api.env` 配置格式。

### 验证

- 新增候选资格、审批状态、拒绝、删除、去重、本地排序、安全上下文、持久化注入、召回指标和非法 Memory Evidence 来源测试。
- 118 项离线测试全部通过；持久化流程使用假模型，未调用真实模型 API，未产生 Token 费用。

---

## V10：Durable Agent Sessions 与 Runtime 幂等恢复

### 新增

- 新增 `session_store.py`，使用 `langgraph-checkpoint-sqlite` 的 `SqliteSaver` 将 LangGraph Checkpoint 持久化到 `.incident_state/incident_pilot.sqlite3`。
- 新增 `incident_sessions` 会话索引，保存调查 ID、问题、Profile、Runtime 可见性、状态、累计计算时间、待处理审批、结果和失败原因。
- 新增 `session_agent.py`，将调查启动与 `Command(resume=...)` 恢复分成可在不同 Python 进程执行的两个入口。
- `main.py` 新增 `new`、`list`、`show <thread_id>` 和 `resume <thread_id>` 子命令；无参数运行仍保留 V9 传统交互模式。
- 新增 `runtime_executions` 幂等账本。每个执行 ID 由 `thread_id + tool_call_id` 稳定派生，账本使用 `BEGIN IMMEDIATE` 原子领取执行权。
- `RunMetrics` 和实验聚合新增 `runtime_replay_count`，区分真正执行和安全返回历史结果。

### 恢复与一致性语义

- `new` 在 LangGraph `interrupt()` 处同步写入 Checkpoint 和待处理审批，程序可立即退出；`resume` 重新打开 SQLite 并从原节点继续。
- 已完成的相同 Runtime 执行不启动新子进程，而是重放原 `ToolResult`。
- 账本为 `running` 但无完成结果时，视为外部副作不确定；系统拒绝自动重跑，而不假设上次执行没发生。
- 这是以安全为优先的 at-most-once 倾向，不宣称外部进程与 SQLite 之间存在无条件 exactly-once 事务。

### 安全

- Checkpoint 使用严格 `JsonPlusSerializer`：关闭 pickle fallback，不允许 MsgPack 从自定义模块动态导入类。
- API Key 不进入 AgentState 或会话表，恢复时从 `api.env` 重新创建模型客户端。
- `.incident_state/` 同时加入 `.gitignore`、文件工具忽略目录和内部保护目录，Agent 不能列出、读取或搜索状态库。
- Runtime 短连接显式提交或回滚并在 `finally` 中关闭，避免 Windows 下 SQLite 文件被残留句柄锁住。

### 兼容性

- `run_agent()` 和无参数 `main.py` 继续使用 `InMemorySaver`，旧调用方无需修改；只有显式使用新 CLI 子命令时才创建持久化数据库。
- `requirements.txt` 新增 `langgraph-checkpoint-sqlite>=3.0.0,<4.0.0`；升级后需要重新安装依赖。
- 普通 Evaluation 仍使用内存状态，不会在批量评测中自动创建持久化会话。

### 验证

- 新增会话索引关闭后重开、原生 LangGraph interrupt 跨 Store 恢复、非法 resume 动作拒绝、API Key 不落盘和状态目录隔离测试。
- 新增 Runtime 已完成结果重放和不确定执行拒绝测试，断言同一执行 ID 只启动一次子进程。
- 110 项离线测试全部通过；使用假模型验证恢复流程，未调用真实模型 API，未产生 Token 费用。

---

## V9：受限 Runtime Evidence 与执行审批

### 新增

- 新增 `run_demo_case(case_id)`。它只能执行 `missing_user_id`、`schema_mismatch`、`connection_leak`、`documentation_required` 四个预登记案例，不接受任意命令、路径、参数或工作目录。
- 新增 `full_runtime` Tool Profile；原有 `code_only`、`code_rag`、`full` 保持不变，普通 `--compare` 仍只运行三组静态工具对照。
- 新增 `runtime_review` LangGraph 节点。交互模式在子进程启动前使用原生 `interrupt()` 暂停，允许批准、拒绝或取消，并从同一 Checkpoint 恢复。
- 新增 Runtime Observation 来源和 `Evidence.runtime_id`。系统为每次真实运行生成 ID，Provenance Validator 要求最终证据的 ID 与绑定 Observation 完全一致。
- 新增 `runtime_required` 评测案例和 `requires_runtime_evidence` 硬通过条件；静态猜对根因但没有真实 Runtime Evidence 仍判失败。
- `RunMetrics` 与实验聚合新增 Runtime 请求、成功、超时、批准和拒绝次数。

### 安全与成本

- Runtime 默认由 `ENABLE_RUNTIME_TOOLS=false` 关闭；关闭时 Schema 在构图前被移除，模型无法请求该工具。
- 交互运行需要“配置开启 + `full_runtime` Profile + 单次人工批准”；执行层仍会再次检查授权和 `MAX_RUNTIME_CALLS`，不能只靠 Prompt 约束。
- 非交互 Evaluation 必须同时选择 `--profile full_runtime` 和 `--allow-runtime`；缺少显式授权时在模型调用前退出，不产生 API 费用或本地执行。
- 子进程使用当前 Python、固定模块入口、固定仓库根目录、参数数组和 `shell=False`；只继承启动所需的最小环境变量，不继承 `API_KEY`；输出中的仓库绝对路径会脱敏，标准输出/错误截断为 4,000 字符，并受 `RUNTIME_TIMEOUT_SECONDS` 控制。
- 默认每次调查最多执行 1 个 Runtime Case；标准对照不会把 Runtime 自动加入原来的实验矩阵。

### 配置与兼容性

- `api.env.example` 新增 `ENABLE_RUNTIME_TOOLS=false`、`MAX_RUNTIME_CALLS=1`、`RUNTIME_TIMEOUT_SECONDS=5`。旧 `api.env` 无需修改，缺省行为等同 V8.1.1，不会暴露或执行 Runtime 工具。
- `run_agent()` 与 `run_agent_detailed()` 末尾新增可选参数 `allow_runtime_execution=False`，旧调用方式保持兼容。
- Evaluation JSON 新增 Runtime Evidence 要求/数量和 Runtime 指标；旧 Case JSON 未提供 `requires_runtime_evidence` 时默认不要求。

### 验证

- 根据首轮真实 `runtime_required` 实验修复两处信息丢失：Runtime Observation 现在把异常类型、异常消息和项目内 traceback 帧放在长 stderr 之前；RAG 使用向量相似度与精确标识符覆盖率的混合得分，避免中文泛词把 `timeout_policy_violation`、`timeout_seconds` 对应供应商契约挤出 Top K。
- 将直接暴露故障标准行为的 `test_demo_app.py` 和 `test_runtime_tools.py` 纳入 Agent 内部文件隔离，避免 Evaluation 被测试实现误导或泄题。
- 新增工具白名单、任意参数拒绝、结构化超时、Runtime 审批/拒绝、系统 ID 来源绑定、Runtime 强制评分、精确契约召回和 Demo 测试隔离测试。
- 103 项离线测试全部通过；测试只运行本地预登记故障夹具，未调用真实模型，未产生 API 费用。
- 修复后的真实 `runtime_required + full_runtime` 验收通过 1/1：根因、代码、文档、引用、Evidence 与 Claim 均为 100%，Runtime 1/1 成功且 confirmed 假设提前收尾；模型调用 8 次、工具调用 10 次、总 Token 38,821。

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
