# Harness Token 用量统计

按需读取 Codex、ZCode 的现有本地记录，以任务或会话查看输入、输出、缓存读取及命中率。默认展示表格，只有明确导出才写报告；不估算缺口，不建设采集服务。

## 1. 安装与调用

需要 Python 3.9 或更新版本，仅使用标准库。安装时将完整 Skill 复制到所选 Harness 的目录，目标已有不同内容会拒绝覆盖：

```bash
python3 agent-token-audit/install_skill.py --harness codex
python3 agent-token-audit/install_skill.py --harness zcode
```

也可用 `--target /绝对路径/agent-token-audit` 安装到自选目录。重新加载 Harness 的 Skill 列表后，使用“统计当前会话的 token 用量”“统计这个任务，排除中间无关轮次”“按原范围重算上次报告”等请求。会话或任务边界有歧义时需要选择候选。

独立命令行入口为 `skills/agent-token-audit/scripts/audit.py`，安装后的同一相对位置也可运行。以模块目录为当前目录：

```bash
python3 skills/agent-token-audit/scripts/audit.py sessions --harness codex
python3 skills/agent-token-audit/scripts/audit.py turns --harness codex --session SESSION_ID
python3 skills/agent-token-audit/scripts/audit.py report --harness codex --session SESSION_ID --turn TURN_1 --turn TURN_3 --to 2026-09-13T20:00:00+08:00
```

`--current` 只使用 Harness 提供的会话环境标识；独立 Shell 中不存在该标识时，请从候选中选择。直接 CLI 默认截止于命令开始，自然语言入口使用请求 ID 或可信请求时间固定截止点。全部参数及操作见 `--help`。

`--format json|csv|markdown` 改变标准输出格式；`--export json --output /目标/报告.json` 才写文件。`show --saved` 展示旧结果，`recompute --saved` 使用旧范围读取当前来源，`recompute --saved --update` 显式更新范围。`--main-only` 排除另列的内部辅助；`--detail model|agent|turn` 的独立视图不再加入总量。

退出码：`0` 为展示/列举成功或确认零用量，`2` 为有效的部分结果、仅计数或仅工具报告，`3` 为不可统计，`4` 为参数/读取错误。部分报告仍应展示。

## 2. 数据来源和计量边界

- Codex：优先读取 `CODEX_HOME/sessions`（默认 `~/.codex/sessions`）的逐调用 `token_usage_record`；同源累计通知不重复加总。旧格式在可对应唯一回复时使用 `last_token_usage`，其余先对完整累计序列差分；混合记录择一计量，跨未选轮次或缺少基线时说明缺口。
- ZCode：默认优先读取现有 `~/.zcode/cli/db/db.sqlite` 中的原始 `model_usage.raw_usage_json`；活跃 WAL 且已有共享内存文件时，用 SQLite 只读事务备份取得一致快照；其他情况复制稳定 DB/WAL 后读取，临时文件用后删除，源数据库不打开为可写。稳定轮次候选合并同会话的 `turn_usage`、`model_usage.turn_id` 与明确轮次事件：只有 usage 时仍可选择和统计，但状态、轮次起止时间保持未知；后续轮次账本或结束事件只补充同一候选。请求以 `session_input.kind=sendText` 为真实输入来源；仅 `promoted_message_id` 能关联其提升后的 message，截止点使用入队接收时间。`synthetic=true` 的 message 会排除且 `--request-id` 明确拒绝；缺少分类或关联字段的旧记录仍单列为未知，不凭正文、时间或 ID 前缀合并。父子轮次关系结合相邻日志目录。没有数据库时读取 rollout 和结构化日志。
- `--source` 指定 JSONL 文件/目录，可重复；`--database` 指定 ZCode 现有数据库。两种 ZCode 计量来源不混合相加：数据库的逻辑消息身份与 rollout 的请求/attempt 身份目前没有可靠的一一映射。需要核查真实重试时，可单独选择保留了逐 attempt usage 的 rollout；数据库报告明确提醒重试缺口。

实现核查覆盖 Codex 0.153.4 及 ZCode 0.16.3/0.16.5 的代表性记录，ZCode 已核对 BigModel Coding Plan 和 Start Plan 的字段。未知供应商字段保留原值及未知状态，不直接加入已知总量。数据库数值列的默认零不替代缺失的 `raw_usage_json`。

缓存读取已包含于输入；缓存写入的源报告零保留但标为语义未确认，推理输出已包含于输出时不再相加。缓存率基于成对已知字段加权；部分字段缺失时只报告已知子集，不推断完整覆盖率。数据库的逻辑请求行数不等于包含全部重试的模型调用数。

子代理按明确关系归属，不按文件名、时间邻近或模型角色判断。Codex 出现压缩标记但没有可关联 usage 时说明缺口。分叉有原始调用身份及祖先来源时排除继承副本，缺少基线或关联时降级；本机尚无用户分叉的真实样例，因此真实分叉覆盖仍待整体验收。时间过滤以完整调用的结束/usage 时间为准，不按比例分割单次调用。

## 3. 开发与验收

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s agent-token-audit/tests -v
```

测试通过外部 CLI 验证统计、范围、去重、状态和文件副作用，构造输入及输出仅写工作区外临时目录。真实数据复算和两种 Harness 的自然语言交互是独立验收要求，不能由自动测试数量替代。

权威行为见[需求](./specs/2026-09-13-agent-token-audit-requirements.md)和[设计](./specs/2026-09-13-agent-token-audit-design.md)。二期的 OpenCode、Claude Code，以及网页、计费和持续采集未实现。

当前自然语言验收：Codex 独立种子轮次已输出正确表格；ZCode 已在桌面端正常授权流程中完成一次真实报告验收，headless 权限客户端不再是该项阻塞。现有仓库记录未保留该次验收的会话身份、固定截止点和复算数值，补记前不得猜测或替换为最新会话。两端歧义候选选择、本轮修复后的桌面回归及真实用户分叉覆盖仍未闭合，CLI 可用不代表一期全部验收完成。
