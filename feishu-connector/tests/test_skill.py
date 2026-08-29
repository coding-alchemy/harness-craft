import unittest
from pathlib import Path


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.skill = (
            Path(__file__).resolve().parents[1]
            / "skills" / "feishu-notify" / "SKILL.md"
        ).read_text(encoding="utf-8")

    def test_uses_bundled_entry_script(self):
        self.assertIn("scripts/feishu_notify.py", self.skill)

    def test_documents_four_stdin_flows(self):
        self.assertIn("stdin", self.skill)
        self.assertIn('"flow": "send"', self.skill)
        self.assertIn('"flow": "task-auto"', self.skill)
        self.assertNotIn('"flow": "notify"', self.skill)

    def test_prohibits_shell_interpolation_and_sensitive_context(self):
        self.assertIn("不得", self.skill)
        self.assertIn("完整日志", self.skill)
        self.assertIn("内部推理", self.skill)

    def test_notification_failure_does_not_change_task_result(self):
        self.assertIn("不得改变原任务结果", self.skill)

    def test_explicit_send_is_single_use_external_authorization(self):
        for required in (
            "即构成本次联网与外发授权",
            "无需再次向用户确认",
            "已配置的固定接收人",
            "用户指定正文",
            "不自动延续到后续消息",
            "平台安全审批",
            "Diff",
            "凭据",
            "内部推理",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.skill)

    def test_bodiless_notifications_use_informative_task_with_single_redaction_retry(self):
        for required in (
            "未指定正文时，生成简短且自包含的任务结果通知",
            "任务标识、核心结果",
            "未完成的具体原因",
            "需要用户决定的事项",
            "密码、API key、访问 Token、Cookie、私钥、验证码",
            "身份证件号、电话号码、私人邮箱、家庭地址",
            "首次发送前",
            "发送进程尚未创建",
            "更安全的替代内容",
            "最多重写一次",
            "投递状态不明",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.skill)
        self.assertNotIn("`notify`", self.skill)
        self.assertNotIn("请回到 Codex", self.skill)

    def test_real_send_requests_network_escalation_on_first_call(self):
        section = self.skill.split("### 执行权限", 1)[1].split(
            "路由按下表选择", 1
        )[0]
        first_send = (
            "用户明确要求发送时，在首个真实发送子命令（`send`、`rich` 或实际发送的 "
            "`task`）调用上直接请求执行器提供的沙箱外联网权限"
        )
        no_sandbox_send = (
            "不得以发送子命令先在网络隔离沙箱中试发或探测飞书连通性"
        )
        offline_diagnostics = (
            "`config` 等明确不联网的诊断不计入真实发送调用，可以在沙箱内执行"
        )
        denied = "遵循「外发授权」的单次隐私脱敏重写条件"
        codex_first_send = (
            "使用 Codex 执行器时，在上述首个真实发送子命令调用上设置 "
            "`sandbox_permissions=require_escalated`"
        )
        for required in (
            first_send,
            no_sandbox_send,
            offline_diagnostics,
            codex_first_send,
            "仅允许 `open.feishu.cn:443`",
            "仍须正常发起并接受平台的工具级权限审批，不得绕过审批",
            denied,
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)
        if all(
            required in section
            for required in (
                first_send,
                no_sandbox_send,
                offline_diagnostics,
                codex_first_send,
            )
        ):
            self.assertLess(
                section.index(first_send), section.index(no_sandbox_send)
            )
            self.assertLess(
                section.index(no_sandbox_send), section.index(offline_diagnostics)
            )
            self.assertLess(
                section.index(offline_diagnostics), section.index(codex_first_send)
            )

    def test_codex_uses_approval_visible_prepare_then_exact_send_command(self):
        text = self.skill
        codex = text.split("### Codex 审批可见调用", 1)[1].split(
            "### 非 Codex stdin 兼容入口", 1
        )[0]
        required = (
            "`prepare-shell`",
            "网络隔离沙箱",
            "只移除 stdout 最后的一个换行",
            "其余命令原样",
            "`sandbox_permissions=require_escalated`",
            "审批拒绝",
            "单次隐私脱敏重写",
            "不回退 stdin、文件或环境变量",
            "`Feishu message sent`",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, codex)
        self.assertLess(codex.index("`prepare-shell`"), codex.index("只移除"))
        self.assertLess(codex.index("只移除"), codex.index("require_escalated"))
        self.assertNotIn("python3 scripts/feishu_notify.py stdin", codex)

    def test_skill_preserves_non_codex_stdin_and_disclosure_limits(self):
        text = self.skill
        compatibility = text.split("### 非 Codex stdin 兼容入口", 1)[1]
        for phrase in (
            "不存在审批前 payload 可见性要求",
            "`stdin`",
            "四种白名单",
            "不得用于 Codex 的真实发送",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, compatibility)
        for phrase in (
            "完整正文会出现在 Codex 工具调用、审批记录和可能的会话记录中",
            "凭据",
            "Token",
            "完整日志",
            "Diff",
            "内部推理",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

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

    def test_documents_cover_shared_interface_and_confirmation_trigger(self):
        frontmatter = self.skill.split("---", 2)[1]
        self.assertIn("任务结果或待确认节点", frontmatter)
        for document in (
            Path(__file__).resolve().parents[1] / "README.md",
            Path(__file__).resolve().parents[1] / "specs" / "feishu-connector.md",
        ):
            with self.subTest(document=document):
                self.assertIn(
                    "Codex 与 OpenCode 共用相同的 argv/stdin 显式接口",
                    document.read_text(encoding="utf-8"),
                )
        usage = (
            Path(__file__).resolve().parents[1] / "docs" / "USAGE.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "直接 argv 与非 Codex stdin 兼容，Codex Shell 发送使用审批可见命令",
            usage,
        )

    def test_frontmatter_describes_all_notification_triggers(self):
        frontmatter = self.skill.split("---", 2)[1]
        for required in ("纯文本", "富文本", "任务通知", "仓库自动通知"):
            with self.subTest(required=required):
                self.assertIn(required, frontmatter)

    def test_documents_cover_project_configuration_selection_order(self):
        for document in (
            Path(__file__).resolve().parents[1] / "README.md",
            Path(__file__).resolve().parents[1] / "docs" / "USAGE.md",
            Path(__file__).resolve().parents[1] / "specs" / "feishu-connector.md",
        ):
            text = document.read_text(encoding="utf-8")
            with self.subTest(document=document):
                self.assertIn("`--project-root` 是全局选项", text)
                self.assertIn("显式路径、Git 项目根目录、当前工作目录", text)

    def test_skill_documents_rich_routing_stdin_network_and_delivery_rules(self):
        for required in (
            "rich --title",
            "用户明确要求任务通知",
            "不得添加 `--auto`",
            "格式信息优先 `rich`",
            "简单短句",
            '"flow": "rich"',
            '"flow": "task"',
            "argv 与网络权限独立",
            "stdin 不提供网络",
            "sent",
            "skipped",
            "退出码 `5`",
            "不得跨进程重试",
            "network.dns",
            "network.timeout",
            "network.tls",
            "network.connection",
            "network.unreachable",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.skill)

    def test_product_documents_cover_rich_stdin_auto_network_and_duplicate_risk(self):
        for document in (
            Path(__file__).resolve().parents[1] / "README.md",
            Path(__file__).resolve().parents[1] / "docs" / "USAGE.md",
            Path(__file__).resolve().parents[1] / "specs" / "feishu-connector.md",
        ):
            text = document.read_text(encoding="utf-8")
            for required in (
                "rich --title",
                '"flow":"rich"',
                '"flow":"task"',
                "任务标识、状态和执行结果",
                "autoNotify=false",
                "network.dns",
                "network.timeout",
                "network.tls",
                "network.connection",
                "network.unreachable",
                "不得跨进程重试",
                "蓝色标题",
                "interactive",
                "plain_text",
                "一个 `lark_md` 正文；不得传入任意消息类型、卡片 JSON 或后台模板",
                "不得传入任意消息类型、卡片 JSON 或后台模板",
            ):
                with self.subTest(document=document, required=required):
                    self.assertIn(required, text)

    def test_readme_v14_summary_states_task_and_permission_contract(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        current_version = readme.split("## 当前版本", 1)[1].split(
            "## 能力边界", 1
        )[0]
        task_summary = (
            "- 用户明确要求发送飞书消息即授权向已配置的固定接收人进行一次显式外发；"
            "未指定正文时使用现有 `task` 发送任务、状态和执行结果；首次发送前脱敏，"
            "仅在发送进程创建前的隐私拒绝允许更安全替代时最多重写一次。"
        )
        expected_summary = (
            "- 用户明确要求真实发送时，Agent 在首个 `send`、`rich` 或实际发送的 "
            "`task` 调用上直接申请受控的沙箱外联网权限；不得先在网络隔离沙箱试发；"
            "`config` 等离线诊断仍可在沙箱内执行。"
        )

        self.assertIn("**V1.4**", current_version)
        self.assertIn(task_summary, current_version)
        self.assertIn(expected_summary, current_version)

    def test_readme_agent_permission_section_matches_skill_contract(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        section = readme.split("### Agent 执行权限", 1)[1].split(
            "```bash", 1
        )[0]
        first_send = (
            "用户明确要求发送时，在首个真实发送子命令（`send`、`rich` 或实际发送的 "
            "`task`）调用上直接请求沙箱外联网权限"
        )
        denied = (
            "联网权限或审批拒绝时，仅满足上述一次隐私脱敏重写条件才重新准备；"
            "否则报告消息未发送，不得退回网络隔离沙箱试发或改用其他渠道绕过审批"
        )
        for required in (
            "`send`、`rich` 和实际发送的 `task` 都需要访问飞书网络",
            first_send,
            "`sandbox_permissions=require_escalated`",
            "仅允许 `open.feishu.cn:443`",
            "不得先在网络隔离沙箱中使用发送子命令试发或探测连通性",
            "`config` 等明确不联网的诊断不计入真实发送调用，可以在沙箱内执行",
            denied,
        ):
            with self.subTest(required=required):
                self.assertIn(required, section)
        self.assertLess(section.index(first_send), section.index("不得先"))
        self.assertLess(section.index("不得先"), section.index("`config`"))
        self.assertLess(section.index("`config`"), section.index(denied))

    def test_product_docs_state_posix_and_96_kib_at_codex_call_site(self):
        root = Path(__file__).resolve().parents[1]
        documents = (
            root / "README.md",
            root / "docs" / "USAGE.md",
        )
        required = (
            "POSIX 操作系统",
            "POSIX Shell",
            "macOS/Linux",
            "96 KiB",
            "98,304 字节",
            "UTF-8",
            "路径、选项和引用开销",
            "PowerShell",
            "`cmd.exe`",
            "不发送、不截断、不拆分、不回退",
        )
        for path in documents:
            text = path.read_text(encoding="utf-8")
            codex = text.split("Codex 审批可见调用", 1)[1].split("非 Codex", 1)[0]
            for phrase in required:
                with self.subTest(document=path.name, phrase=phrase):
                    self.assertIn(phrase, codex)

    def test_current_contract_and_changelog_define_prepare_shell_v13(self):
        root = Path(__file__).resolve().parents[1]
        contract = (root / "specs" / "feishu-connector.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(
            "CLI 子命令为 `send`、`rich`、`task`、`config`、`stdin` 与 "
            "`prepare-shell`。",
            contract,
        )
        for phrase in (
            "`prepare-shell`",
            "stdout",
            "98,304 字节",
            "--project-root=<绝对路径>",
            "退出码 `2`",
            "不读取飞书配置",
        ):
            self.assertIn(phrase, contract)
        self.assertIn("## V1.3 — 2026-08-23", changelog)
        self.assertLess(
            changelog.index("## V1.3 — 2026-08-23"),
            changelog.index("## V1.2 — 2026-08-16"),
        )

    def test_changelog_v12_contract_and_history_are_preserved(self):
        root = Path(__file__).resolve().parents[1]
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = (
            "## V1.2 — 2026-08-16",
            "## V1.1 — 2026-08-13",
            "## V1.0 — 2026-08-12",
        )
        for heading in headings:
            self.assertIn(heading, changelog)
        self.assertLess(changelog.index(headings[0]), changelog.index(headings[1]))
        self.assertLess(changelog.index(headings[1]), changelog.index(headings[2]))

        v12 = changelog.split(headings[0], 1)[1].split(headings[1], 1)[0]
        for required in (
            "Agent 执行权限合同",
            "不改变连接器 CLI、HTTP 发送与进程内重试实现",
            "首个真实发送子命令",
            "不得先在网络隔离沙箱",
            "`config`",
            "联网权限被拒绝",
            "消息未发送",
            "合同测试",
        ):
            with self.subTest(document="CHANGELOG.md", required=required):
                self.assertIn(required, v12)

        historical = changelog[changelog.index(headings[1]):].strip()
        expected_historical = """## V1.1 — 2026-08-13

- 新增通用富文本 `rich`，以带蓝色标题和 `lark_md` 正文的 interactive 卡片发送 Markdown 内容。
- 明确消息路由：标题、分段、列表、链接或代码等格式化信息优先使用富文本，简单短句使用纯文本。
- 区分用户明确要求的显式 `task` 与仓库规则驱动的 `task --auto`；显式通知不受 `notification.autoNotify` 控制。
- stdin 入口支持 `send`、`rich`、`task`、`task-auto` 四种白名单流程，并保证与直接 argv 入口一致的消息语义。
- 明确通知结果状态：只有 `Feishu message sent` 表示已发送，自动通知关闭时报告 `skipped`，避免将成功 no-op 误判为已投递。
- 增加脱敏的网络错误分类，包括 DNS、超时、TLS、连接和不可达类别，便于区分配置问题与执行环境网络问题。
- stdin JSON 严格拒绝重复键，避免字段覆盖造成调用语义不明确。
- 补充重复通知风险说明：进程内重试复用同一 UUID，退出码 `5` 时投递状态可能不明，调用方不得跨进程重试。
- 明确用户的显式发送请求构成本次向固定接收人的外发授权；未指定正文时仅发送任务结果和必要的简短验证信息，且授权不自动延续。

## V1.0 — 2026-08-12

- 支持向已配置用户发送纯文本消息。
- 支持任务完成、任务失败和待确认三种状态的 interactive Markdown 消息卡片。
- 支持环境变量、项目 JSON 和全局 JSON 的分层配置与严格校验。
- 支持由仓库规则控制的自动通知，并在 `notification.autoNotify=false` 时跳过发送。
- 对网络错误、限流和服务端错误执行有限重试，单次逻辑发送复用 UUID 以降低重复发送风险。
- 提供敏感信息脱敏、分类退出码和安全的错误输出。
- 提供不访问真实飞书或凭据的离线测试。
- 提供可重复执行且支持冲突保护的 Skill 安装器。"""
        self.assertEqual(expected_historical, historical)

    def test_changelog_v14_records_task_default_and_single_redaction_retry(self):
        root = Path(__file__).resolve().parents[1]
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## V1.4 — 2026-08-29", changelog)
        self.assertLess(
            changelog.index("## V1.4 — 2026-08-29"),
            changelog.index("## V1.3 — 2026-08-23"),
        )
        v14 = changelog.split("## V1.4 — 2026-08-29", 1)[1].split(
            "## V1.3 — 2026-08-23", 1
        )[0]
        for required in (
            "删除未发布的 `notify` flow",
            "复用现有 `task`",
            "任务、状态和执行结果",
            "最多重写一次",
        ):
            with self.subTest(required=required):
                self.assertIn(required, v14)
