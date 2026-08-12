# 飞书任务通知消息卡片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `task` 通知替换为固定的飞书 `interactive` Markdown 卡片，同时保持显式纯文本 `send`、配置、退出码、重试和安全边界不变。

**Architecture:** CLI 在本地完成新参数验证、状态映射和卡片组装；`send` 继续走 `send_text()`，`task` 改为调用新增的 `send_card()`。客户端抽取私有消息发送流程，使文本和卡片共享 Token 获取、固定 Open ID、UUID、重试和错误分类；stdin 仅将新的严格白名单 JSON 转换为 argv，再复用同一 CLI 路径。

**Tech Stack:** Python 3.9+ 标准库、`argparse`、`json`、`urllib.request`、`unittest` / `unittest.mock`。

## Global Constraints

- 任务 CLI 仅接受 `--status success|failure|confirm`、非空 `--project`、非空 `--conversation`、非空 `--content` 和可选 `--auto`；移除 `--task`、`--summary`、`--repo`、`--branch`、`--source`，不保留兼容层。
- 标题严格为 `<项目名>-<对话框名>-<状态中文>`；`success`→`任务完成`/`green`，`failure`→`任务失败`/`red`，`confirm`→`待确认`/`orange`。
- 项目名和对话框名必须是非空、单行、有效 Unicode，拒绝换行和 NUL；正文必须是非空、有效 Unicode，允许 Markdown 换行，且不被解析、重组、截断或拆分。
- 任务卡片固定为自包含 `interactive`，仅含 `config.wide_screen_mode`、`header.template`、`header.title`（`plain_text`）和一个正文 `div`（`lark_md`）；不支持任意消息类型、卡片 JSON 或后台模板。
- stdin 仅接受 `send` 的现有两字段白名单，或精确的 `task-auto` 新五字段白名单；动态值不进入 Shell 命令字符串。
- `task --auto` 在 `notification.autoNotify=false` 时以退出码 0 no-op，且不得构造客户端或联网；显式 `send` 不受门控。
- 任务取消时 Skill 不调用连接器；失败内容只能是用户可见原因，不能包含内部推理、完整日志或敏感上下文；每个结果或待确认节点最多通知一次，通知失败不得改变原任务结果。
- 重试复用单次逻辑发送的 UUID，不同逻辑发送生成不同 UUID；超出飞书卡片大小限制时保留现有远程错误，不截断或拆分。
- Python 运行时源码仍只在 `feishu-connector/skills/feishu-notify`；Python 3.9+、安装清单、用户级安装及配置/环境变量/退出码保持不变；Codex 与 OpenCode 共用相同显式接口。
- 所有用户审阅文档使用中文；离线测试全用 Mock，不访问真实飞书。

---

## 文件结构

- 修改：`feishu-connector/skills/feishu-notify/scripts/feishu_connector/client.py` — 抽取文本/卡片共用的私有发送流程，公开保留 `send_text()` 并新增受限的 `send_card()`。
- 修改：`feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py` — 定义新任务参数、Unicode/单行验证、`render_task_card()`、新 stdin 白名单，并让任务走 `send_card()`。
- 修改：`feishu-connector/tests/test_client.py` — 对精确 `interactive` 请求体、卡片重试 UUID、大消息远程错误和文本回归做离线断言。
- 修改：`feishu-connector/tests/test_cli.py` — 覆盖渲染、CLI/stdin 输入拒绝、自动门控、错误隔离与 `send` 回归；测试替身同时记录文本与卡片。
- 修改：`feishu-connector/tests/test_skill.py` — 固化 Skill 对新任务参数、取消/失败安全语义和新 stdin JSON 的文档契约。
- 修改：`feishu-connector/skills/feishu-notify/SKILL.md` — 指导 Agent 使用新 argv/stdin 契约，并明确取消、去重和失败内容规则。
- 修改：`feishu-connector/README.md`、`feishu-connector/docs/USAGE.md`、`feishu-connector/specs/feishu-connector.md` — 将用户合同、示例、卡片格式、验收和真实测试步骤更新为中文新行为。

## 公共接口

```python
# feishu_connector.cli
def render_task_card(status, project, conversation, content): ...

# feishu_connector.client
class FeishuClient:
    def send_text(self, message): ...
    def send_card(self, card): ...
```

`render_task_card()` 产生如下精确对象；`FeishuClient.send_card()` 将它 JSON 编码为消息 API 的 `content`，并固定 `msg_type` 为 `interactive`：

```python
{
    "config": {"wide_screen_mode": True},
    "header": {
        "template": "green",
        "title": {"tag": "plain_text", "content": "HETU-个股-二期-架构师-任务完成"},
    },
    "elements": [
        {"tag": "div", "text": {"tag": "lark_md", "content": "- 完成架构设计"}},
    ],
}
```

### Task 1: 为文本和卡片实现共用的飞书发送流程

**Files:**
- Modify: `feishu-connector/skills/feishu-notify/scripts/feishu_connector/client.py:190-209`
- Test: `feishu-connector/tests/test_client.py:214-373`

**Interfaces:**
- Consumes: 既有 `fetch_tenant_access_token()`、`_attempt()`、`_post()`、`config.receive_open_id` 和 `uuid_factory`。
- Produces: `FeishuClient._send_message(msg_type, content)`、`send_text(message)`、`send_card(card)`，与现有未加类型注解的代码风格一致，供 CLI 的显式消息与任务通知调用。

- [ ] **Step 1: 写出失败的卡片传输与幂等测试**

  在 `ClientTests` 中加入下列测试。它要求请求严格包含 `interactive` 与固定卡片对象，证明重试的两次消息请求共享同一个 UUID，并证明飞书拒绝大卡片时不重试、不截断、不拆分：

  ```python
  def test_fetches_token_then_sends_double_encoded_interactive_card(self):
      card = {
          "config": {"wide_screen_mode": True},
          "header": {"template": "green", "title": {"tag": "plain_text", "content": "项目-对话-任务完成"}},
          "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "- 完成"}}],
      }
      transport = FakeTransport([
          JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
          JsonResponse(200, {"code": 0, "msg": "success"}),
      ])
      FeishuClient(self.config(), transport=transport, sleep=lambda _: None).send_card(card)
      message_call = transport.calls[1]
      self.assertEqual("interactive", message_call[2]["msg_type"])
      self.assertEqual(card, json.loads(message_call[2]["content"]))
      self.assertEqual("ou_target1234", message_call[2]["receive_id"])

  def test_card_retry_reuses_one_idempotency_uuid(self):
      transport = FakeTransport([
          JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
          NetworkFailure("response lost"),
          JsonResponse(200, {"code": 0}),
      ])
      client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None,
                            uuid_factory=lambda: "card-send-uuid")
      client.send_card({
          "config": {"wide_screen_mode": True},
          "header": {"template": "green", "title": {"tag": "plain_text", "content": "项目-对话-任务完成"}},
          "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "- 完成"}}],
      })
      calls = [call for call in transport.calls if "/messages?" in call[0]]
      self.assertEqual(["card-send-uuid", "card-send-uuid"], [call[2]["uuid"] for call in calls])

  def test_card_remote_size_error_is_not_retried_split_or_truncated(self):
      content = "长正文" * 10000
      card = {
          "config": {"wide_screen_mode": True},
          "header": {"template": "red", "title": {"tag": "plain_text", "content": "项目-对话-任务失败"}},
          "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
      }
      transport = FakeTransport([
          JsonResponse(200, {"code": 0, "tenant_access_token": "token-value"}),
          JsonResponse(400, {"code": 230001, "msg": "content too large"}),
      ])
      client = FeishuClient(self.config(), transport=transport, sleep=lambda _: None)
      with self.assertRaises(ConnectorError) as caught:
          client.send_card(card)
      message_calls = [call for call in transport.calls if "/messages?" in call[0]]
      self.assertEqual(1, len(message_calls))
      self.assertEqual(card, json.loads(message_calls[0][2]["content"]))
      self.assertEqual(230001, caught.exception.code)
      self.assertFalse(caught.exception.retryable)

  def test_separate_text_and_card_sends_use_different_uuids(self):
      identifiers = iter(("text-send-uuid", "card-send-uuid"))
      transport = FakeTransport([
          JsonResponse(200, {"code": 0, "tenant_access_token": "token-one"}),
          JsonResponse(200, {"code": 0}),
          JsonResponse(200, {"code": 0, "tenant_access_token": "token-two"}),
          JsonResponse(200, {"code": 0}),
      ])
      client = FeishuClient(
          self.config(),
          transport=transport,
          sleep=lambda _: None,
          uuid_factory=lambda: next(identifiers),
      )
      client.send_text("first")
      client.send_card({
          "config": {"wide_screen_mode": True},
          "header": {"template": "orange", "title": {"tag": "plain_text", "content": "项目-对话-待确认"}},
          "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "请选择"}}],
      })
      calls = [call for call in transport.calls if "/messages?" in call[0]]
      self.assertEqual(
          ["text-send-uuid", "card-send-uuid"],
          [call[2]["uuid"] for call in calls],
      )
  ```

  用最后一个测试替换既有 `test_separate_logical_sends_use_different_uuids`，使同一断言同时覆盖文本与卡片两个公开入口。

- [ ] **Step 2: 运行新增测试，确认当前实现失败**

  Run: `python3 -m unittest feishu-connector.tests.test_client.ClientTests.test_fetches_token_then_sends_double_encoded_interactive_card feishu-connector.tests.test_client.ClientTests.test_card_retry_reuses_one_idempotency_uuid feishu-connector.tests.test_client.ClientTests.test_card_remote_size_error_is_not_retried_split_or_truncated -v`

  Expected: FAIL，报 `AttributeError: 'FeishuClient' object has no attribute 'send_card'`。

- [ ] **Step 3: 抽取私有发送函数并实现受限的 `send_card()`**

  用以下实现替换现有 `send_text()`，避免复制 Token、UUID、重试或错误分类逻辑；`send_card()` 只接受卡片对象并固定消息类型，不增加“任意 msg_type”公共接口：

  ```python
  def _send_message(self, msg_type, content):
      token = self.fetch_tenant_access_token()
      payload = {
          "receive_id": self.config.receive_open_id,
          "msg_type": msg_type,
          "content": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
          "uuid": str(self.uuid_factory()),
      }
      return self._attempt(
          lambda: self._post(
              self.MESSAGE_URL,
              {"Authorization": "Bearer %s" % token},
              payload,
          )
      )

  def send_text(self, message):
      return self._send_message("text", {"text": message})

  def send_card(self, card):
      return self._send_message("interactive", card)
  ```

- [ ] **Step 4: 运行客户端测试，确认卡片与文本行为均通过**

  Run: `python3 -m unittest feishu-connector.tests.test_client -v`

  Expected: PASS；既有文本双重 JSON 编码、网络重试、不同逻辑发送的 UUID 和远程错误分类全部保持通过。

- [ ] **Step 5: 提交客户端边界改动**

  ```bash
  git add feishu-connector/skills/feishu-notify/scripts/feishu_connector/client.py feishu-connector/tests/test_client.py
  git commit -m "feat: add Feishu interactive card sender"
  ```

### Task 2: 替换任务 CLI 为严格的卡片输入与渲染器

**Files:**
- Modify: `feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py:37-180`
- Modify: `feishu-connector/tests/test_cli.py:24-250, 358-372, 540-620`

**Interfaces:**
- Consumes: Task 1 的 `FeishuClient.send_card(card)`；现有 `config_from_settings()` 和自动门控顺序。
- Produces: `_validate_task_text(name, value, single_line=False)`、`task_content(value)`、`single_line_non_empty(value)`、`render_task_card(status, project, conversation, content)`、只包含新字段的 `task` argv，以及执行 `client_factory(config).send_card(card)` 的任务发送分支。既有 `non_empty()` 保持不变，继续服务显式 `send --message`。

- [ ] **Step 1: 将测试替身和导入改为卡片断言，并写失败测试**

  将 `FakeClient` 完整改为分别记录文本和卡片；`setUp()` 同步清空两个列表，并把既有 `FakeClient.sent` 断言按命令类型改为 `sent_text` 或 `sent_cards`：

  ```python
  class FakeClient:
      sent_text = []
      sent_cards = []
      configs = []
      error = None

      def __init__(self, config):
          self.config = config
          self.configs.append(config)

      def send_text(self, message):
          if self.error is not None:
              raise self.error
          self.sent_text.append(message)

      def send_card(self, card):
          if self.error is not None:
              raise self.error
          self.sent_cards.append(card)
  ```

  `setUp()` 中对应的重置代码为：

  ```python
  FakeClient.sent_text = []
  FakeClient.sent_cards = []
  FakeClient.configs = []
  FakeClient.error = None
  ```

  将导入更新为 `from feishu_connector.cli import main, render_task_card`，并加入状态映射、非法状态、完整 Unicode 单行边界、正文边界与精确结构测试：

  ```python
  def test_render_task_card_uses_exact_title_color_and_markdown(self):
      self.assertEqual(
          {
              "config": {"wide_screen_mode": True},
              "header": {"template": "green", "title": {"tag": "plain_text", "content": "HETU-个股-二期-架构师-任务完成"}},
              "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "**结果**\n\n- 评审通过"}}],
          },
          render_task_card("success", "HETU", "个股-二期-架构师", "**结果**\n\n- 评审通过"),
      )

  def test_render_task_card_maps_all_statuses(self):
      for status, label, color in (("success", "任务完成", "green"), ("failure", "任务失败", "red"), ("confirm", "待确认", "orange")):
          with self.subTest(status=status):
              card = render_task_card(status, "项目", "对话", "正文")
              self.assertEqual("项目-对话-" + label, card["header"]["title"]["content"])
              self.assertEqual(color, card["header"]["template"])

  def test_render_task_card_rejects_invalid_status(self):
      for status in ("cancel", "SUCCESS", "", None):
          with self.subTest(status=status):
              with self.assertRaisesRegex(ValueError, "status"):
                  render_task_card(status, "项目", "对话", "正文")

  def test_render_task_card_validates_title_fields_and_content(self):
      line_breaks = ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
      for field in ("project", "conversation"):
          for value in ("", "   ", "a\x00b", "\ud800") + tuple("a%sb" % char for char in line_breaks):
              with self.subTest(field=field, value=repr(value)):
                  arguments = {"status": "success", "project": "项目", "conversation": "对话", "content": "正文"}
                  arguments[field] = value
                  with self.assertRaisesRegex(ValueError, field):
                      render_task_card(**arguments)
      for value in ("", "   ", "a\x00b", "\ud800"):
          with self.subTest(content=repr(value)):
              with self.assertRaisesRegex(ValueError, "content"):
                  render_task_card("success", "项目", "对话", value)
      multiline = "第一行\n第二行\u2028第三行"
      card = render_task_card("success", "项目", "对话", multiline)
      self.assertEqual(multiline, card["elements"][0]["text"]["content"])

  def test_task_sends_card_and_explicit_send_stays_plain_text(self):
      code, _, stderr = self.invoke([
          "task", "--status", "success", "--project", "HETU",
          "--conversation", "个股", "--content", "- 完成",
      ])
      self.assertEqual(0, code)
      self.assertEqual(1, len(FakeClient.sent_cards))
      self.assertEqual([], FakeClient.sent_text)
      self.assertEqual("", stderr)

      code, _, stderr = self.invoke(["send", "--message", "hello 飞书"])
      self.assertEqual(0, code)
      self.assertEqual(["hello 飞书"], FakeClient.sent_text)
      self.assertEqual(1, len(FakeClient.sent_cards))
      self.assertEqual("", stderr)

  def test_explicit_send_keeps_existing_nul_behavior(self):
      code, _, stderr = self.invoke(["send", "--message", "a\x00b"])
      self.assertEqual(0, code)
      self.assertEqual(["a\x00b"], FakeClient.sent_text)
      self.assertEqual("", stderr)

  @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
  def test_old_task_parameters_have_no_compatibility_layer(self):
      result = self.run_cli_with_bytes([
          b"task", b"--status", b"success", b"--task", b"old",
          b"--summary", b"old", b"--repo", b"repo", b"--branch", b"branch",
          b"--source", b"Codex",
      ])
      self.assertEqual(2, result.returncode)

  @unittest.skipUnless(os.name == "posix", "POSIX byte argv semantics required")
  def test_direct_cli_rejects_non_utf8_new_task_fields_before_configuration(self):
      for invalid_field in ("project", "conversation", "content"):
          values = {"project": b"project", "conversation": b"conversation", "content": b"content"}
          values[invalid_field] = b"invalid-\xff"
          with self.subTest(field=invalid_field):
              result = self.run_cli_with_bytes([
                  b"task", b"--status", b"success",
                  b"--project", values["project"],
                  b"--conversation", values["conversation"],
                  b"--content", values["content"],
              ])
              self.assertEqual(2, result.returncode)
              self.assertIn(b"valid Unicode", result.stderr)
              self.assertNotIn(b"configuration error", result.stderr)
  ```

  上述测试替换旧任务模板和 OpenCode `--source` 测试；其他既有配置、自动门控、退出码和日志测试只需把任务 argv 与 `FakeClient` 断言改为新接口。

- [ ] **Step 2: 运行 CLI 渲染与参数测试，确认当前实现失败**

  Run: `python3 -m unittest feishu-connector.tests.test_cli.CliTests.test_render_task_card_uses_exact_title_color_and_markdown feishu-connector.tests.test_cli.CliTests.test_render_task_card_maps_all_statuses -v`

  Expected: FAIL，测试模块先因无法导入 `render_task_card` 而失败；实现步骤完成后，新参数测试才可进入执行。

- [ ] **Step 3: 实现单行验证、固定卡片渲染和新命令参数**

  保持既有 `non_empty()` 原样，新增只用于任务字段的验证函数；用 Unicode `str.splitlines()` 所覆盖的全部换行字符集合实现“单行”，并用以下实现完全替换 `render_task_message()`：

  ```python
  TASK_STATUS = {
      "success": ("任务完成", "green"),
      "failure": ("任务失败", "red"),
      "confirm": ("待确认", "orange"),
  }

  LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")

  def _validate_task_text(name, value, single_line=False):
      if not isinstance(value, str):
          raise ValueError("%s must be text" % name)
      try:
          value.encode("utf-8")
      except UnicodeEncodeError as exc:
          raise ValueError(
              "%s must contain valid Unicode scalar text" % name
          ) from exc
      if not value.strip() or "\x00" in value:
          raise ValueError("%s must not be empty or contain NUL" % name)
      if single_line and any(char in LINE_BREAKS for char in value):
          raise ValueError("%s must be a single line" % name)
      return value

  def _task_argument(name, value, single_line=False):
      try:
          return _validate_task_text(name, value, single_line=single_line)
      except ValueError as exc:
          raise argparse.ArgumentTypeError(str(exc)) from exc

  def single_line_non_empty(value):
      return _task_argument("value", value, single_line=True)

  def task_content(value):
      return _task_argument("content", value)

  def render_task_card(status, project, conversation, content):
      try:
          label, color = TASK_STATUS[status]
      except (KeyError, TypeError) as exc:
          raise ValueError("status must be success, failure, or confirm") from exc
      project = _validate_task_text("project", project, single_line=True)
      conversation = _validate_task_text("conversation", conversation, single_line=True)
      content = _validate_task_text("content", content)
      return {
          "config": {"wide_screen_mode": True},
          "header": {"template": color, "title": {"tag": "plain_text", "content": "%s-%s-%s" % (project, conversation, label)}},
          "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
      }
  ```

  将顶层 parser 描述改为同时包含纯文本和任务卡片；将 `task_parser` 设为 `choices=tuple(TASK_STATUS)`，并只注册 `--project`、`--conversation`（`type=single_line_non_empty`）和 `--content`（`type=task_content`）；删除旧五个参数。`_run_main()` 的 `send` 分支保持 `send_text(args.message)`，`task` 分支调用 `render_task_card(args.status, args.project, args.conversation, args.content)` 后调用 `send_card(card)`。自动门控必须仍位于渲染、`config_from_settings()` 和客户端构造之前。

- [ ] **Step 4: 运行整个 CLI 测试模块，确认任务卡片和既有 CLI 语义通过**

  Run: `python3 -m unittest feishu-connector.tests.test_cli -v`

  Expected: PASS；三种状态、精确固定结构、输入边界、文本 `send`、配置/退出码、自动 no-op 与错误隔离均通过。

- [ ] **Step 5: 提交 CLI 卡片替换改动**

  ```bash
  git add feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py feishu-connector/tests/test_cli.py
  git commit -m "feat: render task notifications as Feishu cards"
  ```

### Task 3: 收紧 stdin 白名单并证明它复用自动卡片路径

**Files:**
- Modify: `feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py:108-130`
- Modify: `feishu-connector/tests/test_cli.py:400-620`

**Interfaces:**
- Consumes: Task 2 的新 `task` argv 和 `render_task_card()`；既有 `main()` 的 `json.load(stdin)` 与二次 `parser.parse_args()`。
- Produces: `_stdin_argv(payload)`，返回 argv 列表或 `None`，仅把合法 `task-auto` JSON 转为 `task --auto --status ... --project ... --conversation ... --content ...`；不引入 Python 3.10 的 `list[str] | None` 注解。

- [ ] **Step 1: 写失败的 stdin 白名单、无 Shell 与自动门控测试**

  在 CLI 测试中替换旧 task stdin payload，并添加：

  ```python
  def test_stdin_task_auto_sends_same_card(self):
      literal_content = "请选择 A 或 B；不要执行 $(touch /tmp/feishu-shell-marker)"
      payload = {"flow": "task-auto", "status": "confirm", "project": "HETU", "conversation": "架构师", "content": literal_content}
      code, _, stderr = self.invoke(["stdin"], stdin=io.StringIO(json.dumps(payload)))
      self.assertEqual(0, code)
      self.assertEqual("HETU-架构师-待确认", FakeClient.sent_cards[0]["header"]["title"]["content"])
      self.assertEqual(literal_content, FakeClient.sent_cards[0]["elements"][0]["text"]["content"])
      self.assertEqual("", stderr)

  def test_stdin_task_rejects_non_whitelisted_or_invalid_payloads(self):
      class ClientMustNotStart:
          def __init__(self, config):
              raise AssertionError("invalid stdin constructed a client")

      for payload in (
          {"flow": "task-auto", "status": "success", "task": "old", "summary": "old", "repo": "r", "branch": "b"},
          {"flow": "task-auto", "status": "success", "project": "p", "conversation": "c", "content": "x", "source": "Codex"},
          {"flow": "task-auto", "status": "success", "project": "p", "conversation": "c"},
          {"flow": "task-auto", "status": "cancel", "project": "p", "conversation": "c", "content": "x"},
          {"flow": "task-auto", "status": "success", "project": "p", "conversation": "c", "content": None},
      ):
          with self.subTest(payload=payload):
              code, _, stderr = self.invoke(["stdin"], client_factory=ClientMustNotStart, stdin=io.StringIO(json.dumps(payload)))
              self.assertEqual(2, code)
              self.assertEqual("Invalid stdin input\n", stderr)

  def test_stdin_task_auto_disabled_does_not_construct_client(self):
      class ClientMustNotStart:
          def __init__(self, config):
              raise AssertionError("disabled auto task constructed a client")

      payload = {"flow": "task-auto", "status": "success", "project": "p", "conversation": "c", "content": "x"}
      code, stdout, stderr = self.invoke(
          ["stdin"],
          environ={"FEISHU_AUTO_NOTIFY": "false"},
          client_factory=ClientMustNotStart,
          stdin=io.StringIO(json.dumps(payload)),
      )
      self.assertEqual(0, code)
      self.assertIn("disabled", stdout)
      self.assertEqual("", stderr)
  ```

  第一个测试中的 Shell 元字符必须原样进入 Markdown 字段；测试本身不启动 Shell。最后一个测试证明新 JSON 路径在自动通知关闭时不构造客户端、不联网。

- [ ] **Step 2: 运行 stdin 测试，确认旧转换器拒绝新字段**

  Run: `python3 -m unittest feishu-connector.tests.test_cli.CliTests.test_stdin_task_auto_sends_same_card feishu-connector.tests.test_cli.CliTests.test_stdin_task_rejects_non_whitelisted_or_invalid_payloads -v`

  Expected: FAIL；新五字段 payload 被判为 `Invalid stdin input`。

- [ ] **Step 3: 用精确新字段替换 task stdin 转换器**

  将 `_stdin_argv()` 中任务白名单和 argv 构造替换为：

  ```python
  task_keys = {"flow", "status", "project", "conversation", "content"}
  if set(payload) != task_keys or payload.get("flow") != "task-auto":
      return None
  fields = ("status", "project", "conversation", "content")
  if not all(isinstance(payload.get(field), str) for field in fields):
      return None
  return [
      "task", "--auto",
      "--status", payload["status"],
      "--project", payload["project"],
      "--conversation", payload["conversation"],
      "--content", payload["content"],
  ]
  ```

  不在 stdin 代码中执行命令、调用 Shell 或自行发送网络请求；让二次 argparse 解析统一执行 status、Unicode、空值、换行和 NUL 校验。

- [ ] **Step 4: 运行 stdin 与完整离线回归**

  Run: `python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v`

  Expected: PASS；所有 stdin 测试与安装、配置、文本、卡片客户端测试均为离线 Mock 测试。

- [ ] **Step 5: 提交安全 stdin 改动**

  ```bash
  git add feishu-connector/skills/feishu-notify/scripts/feishu_connector/cli.py feishu-connector/tests/test_cli.py
  git commit -m "feat: accept task card requests from safe stdin"
  ```

### Task 4: 更新 Skill 与中文用户合同

**Files:**
- Modify: `feishu-connector/skills/feishu-notify/SKILL.md`
- Modify: `feishu-connector/README.md`
- Modify: `feishu-connector/docs/USAGE.md`
- Modify: `feishu-connector/specs/feishu-connector.md`
- Modify: `feishu-connector/tests/test_skill.py`

**Interfaces:**
- Consumes: Tasks 1–3 已固定的 task argv、task-auto JSON、卡片结构与错误/自动通知语义。
- Produces: 面向 Agent 与使用者的一致中文调用合同，以及防止今后文档回退到旧字段的离线文档测试。

- [ ] **Step 1: 添加失败的 Skill 文档契约测试**

  在 `SkillContractTests` 增加精确文本检查，先让当前文档失败：

  ```python
  def test_documents_card_task_contract_and_safety_rules(self):
      for required in (
          "--project", "--conversation", "--content", '"project"',
          '"conversation"', '"content"', "手动取消", "最多执行一次",
          "用户可见原因", "完整日志", "内部推理", "消息卡片",
          "success", "failure", "confirm",
      ):
          with self.subTest(required=required):
              self.assertIn(required, self.skill)
      for removed in ("--task", "--summary", "--repo", "--branch", "--source"):
          self.assertNotIn(removed, self.skill)
  ```

- [ ] **Step 2: 运行 Skill 文档测试，确认其暴露旧调用契约**

  Run: `python3 -m unittest feishu-connector.tests.test_skill.SkillContractTests.test_documents_card_task_contract_and_safety_rules -v`

  Expected: FAIL，旧 `SKILL.md` 缺少新参数，且仍列出被移除的字段。

- [ ] **Step 3: 同步四份中文文档**

  在四份文档中统一完成以下具体替换：

  ```markdown
  python3 "$ENTRY" task --auto --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择 A 或 B"
  ```

  - 将连接器能力表述改为“显式 `send` 发送纯文本；`task` 发送自包含 interactive Markdown 卡片”。
  - 列出三个状态的中文标题/颜色映射，展示 `plain_text` 标题和 `lark_md` 正文的固定 JSON，且说明正文原样传递、不得传入任意卡片 JSON。
  - 用精确新五字段 JSON 替换所有 `task-auto` stdin 示例，保留 `send` 两字段示例与“独立 stdin、禁止动态 Shell 拼接”。
  - 明确项目名/对话框名单行有效 Unicode、正文允许 Markdown 换行，NUL/空值拒绝，超过飞书限制不截断或拆分。
  - 明确手动取消不调用连接器、每个最终结果或待确认节点只通知一次、失败只给用户可见原因且不泄露内部推理/完整日志/敏感上下文、通知错误不改变任务结果。
  - 保留配置、环境变量、退出码、重试/UUID、安装器和 Python 3.9+ 合同；更新真实验收为在测试用户上分别发送完成、失败、待确认三张卡片，并保留一次纯文本 `send` 验收。

- [ ] **Step 4: 运行文档与完整离线测试**

  Run: `python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v`

  Expected: PASS；`test_skill.py` 和全部 Python 行为测试通过，且没有真实飞书请求。

- [ ] **Step 5: 提交文档合同更新**

  ```bash
  git add feishu-connector/skills/feishu-notify/SKILL.md feishu-connector/README.md feishu-connector/docs/USAGE.md feishu-connector/specs/feishu-connector.md feishu-connector/tests/test_skill.py
  git commit -m "docs: document Feishu task notification cards"
  ```

### Task 5: 完成可安装性验证与受控真实验收

**Files:**
- Verify only: `feishu-connector/install_skill.py`
- Verify only: `feishu-connector/skills/feishu-notify/**`
- Verify only: `feishu-connector/tests/test_*.py`

**Interfaces:**
- Consumes: 完整的源码 Skill 与现有六文件安装清单；只有经操作者明确授权后才消费其用户级安装目录和测试配置。
- Produces: 离线测试证据、安装器回归证据，以及仅在操作者明确授权后的升级结果和测试用户验收记录。

- [ ] **Step 1: 运行最终全量离线测试**

  Run: `python3 -m unittest discover -s feishu-connector/tests -p 'test_*.py' -v`

  Expected: PASS，输出没有真实 Token、Open ID、Authorization、网络访问或失败测试。

- [ ] **Step 2: 仅用 Mock 验证安装器清单和覆盖语义**

  Run: `python3 -m unittest feishu-connector.tests.test_installer -v`

  Expected: PASS；测试临时目录中的六个受管文件、权限、幂等安装、冲突拒绝和 `--force` 覆盖语义均通过，不写入用户真实的 `${CODEX_HOME:-~/.codex}`。

- [ ] **Step 3: 获得明确授权后升级用户级 Skill**

  这是会覆盖用户级受管 Skill 文件的发布操作。只有操作者明确要求安装或升级后才运行：

  ```bash
  python3 feishu-connector/install_skill.py --force
  ```

  Expected: 输出 `Installed 6 feishu-notify Skill files`。若未获授权、目标不可写或安装器返回非零，不改用更强覆盖手段；保留源码实现和离线测试结果，并把该步骤记录为未执行。

- [ ] **Step 4: 在用户明确提供测试配置并授权发送后执行真实验收**

  在同一 Shell 会话中先声明安装入口，运行 `config` 并确认输出只显示来源与脱敏标识；随后仅向测试用户分别执行：

  ```bash
  ENTRY="${CODEX_HOME:-$HOME/.codex}/skills/feishu-notify/scripts/feishu_notify.py"
  python3 "$ENTRY" config
  python3 "$ENTRY" send --message "飞书连接器纯文本验收"
  python3 "$ENTRY" task --status success --project "HETU" --conversation "个股-二期-架构师" --content "- 完成架构设计"
  python3 "$ENTRY" task --status failure --project "HETU" --conversation "个股-二期-架构师" --content "- 数据源不可用，请检查测试配置"
  python3 "$ENTRY" task --status confirm --project "HETU" --conversation "个股-二期-架构师" --content "请选择继续方案 A 或 B"
  ```

  Expected: 一条原样 text 和三张标题/颜色分别为绿“任务完成”、红“任务失败”、橙“待确认”的卡片；正文 Markdown 原样呈现。若未明确配置测试凭据或未获准实际发送，则记录为未执行，不以网络验证替代离线测试。

- [ ] **Step 5: 检查格式与实现差异**

  Run: `git diff --check`

  Expected: 无输出并返回 0。

  Run: `git status --short`

  Expected: 状态仅包含此功能的源码、测试和文档改动，或为空（若每个任务均已提交）。

## 计划自检

- 设计的三状态映射、严格标题、精确 interactive 结构、Markdown 原样正文、Unicode/NUL/换行边界、新 stdin 白名单、自动门控、失败隔离、UUID 重试、文本回归、中文文档和真实测试用户验收均有明确任务覆盖。
- 计划未引入平台 Adapter、动态接收人、任意卡片、模板 ID、按钮、截断、拆分或旧参数兼容层。
- 代码接口一致：CLI `render_task_card()` 产出 `dict`，任务调用 `send_card(card)`，客户端将卡片作为 JSON `content` 以 `interactive` 类型发送；stdin 仅复用新 task argv。
- 已检查计划文本，不含占位标记或未定义接口引用。
