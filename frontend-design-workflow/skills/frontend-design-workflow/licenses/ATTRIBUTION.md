# 来源与修改声明

当前方法改编自 daymade 的 `design-system-builder` 与 `ui-blueprint`，均为 MIT License，Copyright (c) 2025 daymade。完整许可见 [daymade-MIT.txt](daymade-MIT.txt)。

固定来源为用户提供的两个包（取得日期 2026-10-16）：

- design-system-builder.skill SHA-256 `7ec0cc719d560f92748b19b5a0a490da299eb425a8c4434298ae0c915cd76cef`
- ui-blueprint.skill SHA-256 `0982d0fafc3c659819c272c851ffd76fa0e36bdd95a21288dd8afb5bfe3df647`

2026-10-16 改编：合并重复的内容优先、排版层级、视觉密度、组件一致性与反馈方法；保留局部任务所需规则，将强制完整 PRD、固定 React/Tailwind/Lucide、固定方案数量、自动目录写入和子代理步骤改为服从当前任务。模型控制措辞不移植。新增代表对象先行验证与证据边界，使方法适配已有页面和仅评估任务。

原文只供维护回查；运行所需方法均在本 Skill 内。方法广泛效果尚待真实使用验证。

## 视觉方向新增来源（2026-10-16）

- Anthropic `frontend-design`，固定 commit `dbd4588f9e1033efb41dad4bef2f7947c8993d44`，[固定来源](https://github.com/anthropics/skills/tree/dbd4588f9e1033efb41dad4bef2f7947c8993d44/skills/frontend-design)，适用 [Apache 2.0](anthropic-Apache-2.0.txt)。该目录无额外 NOTICE。本文及 visual-direction.md 改编内容语境、字体角色、方向校准和克制方法；通用绝对偏好改为依当前简报选择，不要求每次新增风格或完整方案。
- Ty Farrago / taste，固定 commit `acbb3e9c9051e096cb9e5e5cc1af88d56bc05459`，[固定来源](https://github.com/tyfarrago-hub/taste/tree/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459)，Copyright (c) 2026 Ty Farrago，适用 [MIT](taste-MIT.txt)，具体归属见原样 [CREDITS](taste-CREDITS.md)。`emil-design-eng` 为 Ty 的原创整理，灵感归属 Emil Kowalski / animations.dev；`stitch-design-taste` 面向 Google Stitch，Google 不是作者。

`references/materials/taste/` 保存以下原样资料（参考用途，非独立执行入口）：shape、brandkit、website、image-to-code、gpt-taste、emil-design-eng、stitch-design-taste（含 DESIGN.md）、cosmic-glass-dashboard（含 theme.css / starter.html）。本地参考合并其产品语境、参考提取、规则表达和风格例子；原文特有参数、例子仍可按需查阅，效果均待场景验证。原文以 original.md 命名以避免作为额外 Skill 入口，字节不改写；原生依赖、命令、生成数量、安装/部署和控制措辞不被导入。本地参考说明的条件与当前任务要求决定采用部分。

六项第三方来源的固定入口如下：原作者 lexnlin / learn2vibecode.dev（GitHub Leonxlnx），经 taste 收录，CREDITS 称原项目无许可；本 Skill 不分发或改编其正文，仅保留来源候选与待澄清状态：

- [design-taste-frontend](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/design-taste-frontend/SKILL.md)
- [high-end-visual-design](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/high-end-visual-design/SKILL.md)
- [minimalist-ui](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/minimalist-ui/SKILL.md)
- [industrial-brutalist-ui](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/industrial-brutalist-ui/SKILL.md)
- [redesign-existing-projects](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/redesign-existing-projects/SKILL.md)
- [full-output-enforcement](https://github.com/tyfarrago-hub/taste/blob/acbb3e9c9051e096cb9e5e5cc1af88d56bc05459/skills/full-output-enforcement/SKILL.md)

## 专项方法新增（2026-10-16）

improvement-techniques.md 合并 taste 的 layout、typeset、colorize、animate、clarify、adapt、harden、optimize、bolder、quieter、distill、delight、overdrive、critique、audit、polish（同一固定 commit，Ty Farrago 原创范围，MIT）。保留可操作数值、代码形态与场景例子；把强制 impeccable 前置、检测器、固定输出/问题数、平台断言和无关产品扩展改为本地条件性方法，不移植外部运行工作流。原样正文仅供维护回查，不要求独立使用者读取源码外层。

critique 的 reference/cognitive-load.md 中 Memory Bridge 与 Context Switch 改编为评审章节的“跨步骤上下文”和“决策信息并置”；保留触发条件与具体做法，确认页、报价的例子为本地情境化表达。不引入原参考的固定记忆容量断言、选项数量或评分阈值。

imagegen-frontend-web/mobile 的原样正文已随包保留在 references/materials/taste/ 同名目录：只有当前请求需要生成参考、能力与授权具备时参考，按实际需要决定图数；它们关于 Web 每区一图、移动端逐屏一致性/安全区/设备框、风格和布局的详细例子保留为待验证候选。原文强制控制措辞不执行，未集成生成服务，不宣称生成/原生流程已通过验收。

impeccable 入口声明 Apache 2.0、基于 Anthropic，并引用 NOTICE.md；本次快照缺该 NOTICE，且原生入口有脚本和路径模板。该条目保持来源/方法与工具链核对候选，未复制其正文或脚本。ui-ux-pro-max 的作者/数据归属未独立确认，保留可检索资料与 Python/CSV 工具候选，未分发其正文、脚本或数据。初版无必须安装或已集成的外部可选执行依赖。
