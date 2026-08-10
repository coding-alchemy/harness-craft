# 飞书连接器用户级安装器设计

## 目标

为飞书连接器提供一个仅依赖 Python 3 标准库的 macOS/Linux 用户级安装器，使 CLI、Shell-only 适配器和 Codex Skill 可以从任意项目稳定调用，不再依赖源码仓库位置或当前工作目录。

连接器的消息发送、配置、可靠性和安全行为以 [`feishu-connector.md`](feishu-connector.md) 为准，本设计只定义安装与更新行为。

## 范围

- 新增 `feishu-connector/install.py`。
- 安装连接器运行文件、两个稳定命令入口和 Codex Skill。
- 支持幂等重复安装和显式 `--force` 更新。
- 安装后检查文件、权限、入口和 Skill。
- 在 README 和快速使用指南中说明安装、更新、PATH 与源码直接运行方式。

第一版不支持 Windows，不安装第三方依赖，不实现卸载器，不自动修改 Shell 配置，不创建或修改飞书配置，也不读取或迁移 Secret。

## 安装位置

默认用户级路径固定为：

- 运行文件：`~/.local/share/feishu-connector/scripts/`
- CLI 入口：`~/.local/bin/feishu-notify`
- 适配器入口：`~/.local/bin/feishu-notify-adapter`
- Codex Skill：`${CODEX_HOME:-~/.codex}/skills/feishu-notify/SKILL.md`

`CODEX_HOME` 只影响 Skill 目标目录；连接器运行文件与命令入口仍使用上述 `~/.local` 路径。

## 文件发布与更新

安装器维护一组明确的受管文件，并以原子替换发布每个目标文件：

- 目标不存在时创建。
- 目标内容与权限均和待安装文件相同时视为成功，重复安装不产生额外变化。
- 目标内容相同但权限不同时，默认拒绝原地修改；只有显式传入 `--force` 时才用新 inode 替换目标，避免修改硬链接别名。
- 目标内容不同时默认拒绝覆盖并返回非零退出码。
- 只有显式传入 `--force` 时才替换内容不同的受管文件。

安装器不得删除目标目录、遍历删除旧文件、覆盖受管列表以外的文件或修改飞书配置目录。临时文件必须创建在目标文件所在目录，写入成功并设置权限后再原子发布；目标原先缺失且未传 `--force` 时使用操作系统的原子 no-clobber rename。失败后不得通过存在身份竞态的 pathname unlink 清理；应把仍打开的 staging inode 收紧为 `0600`，保留并报告经过身份验证的恢复路径，同时不破坏原目标。

## 稳定命令入口

两个 `~/.local/bin` 入口使用安装后脚本的绝对路径：

- `feishu-notify` 调用已安装的 `feishu_notify.py`，原样转发所有 argv。
- `feishu-notify-adapter` 调用已安装的 `feishu_notify_adapter.py`，保留 stdin、stdout、stderr 和退出码。

入口不得对消息或任务字段做 Shell 求值。参数转发必须保持每个调用参数的边界，适配器标准输入必须原样传递。

Codex Skill 改为调用 `feishu-notify` 和 `feishu-notify-adapter`，不再引用 `feishu-connector/scripts/...` 相对路径。安装完成后若 `~/.local/bin` 不在 `PATH`，安装器输出明确提示，但不修改 `.zshrc`、`.bashrc` 或其他 Shell 配置。

## 安全边界

安装器不得读取或写入以下内容：

- `~/.config/feishu-connector/config.json`
- 项目 `.config/feishu-connector/config.json`
- 遗留 `feishu-connector/.env` 的内容
- App Secret、Tenant Access Token 或 Open ID

安装器只报告受管文件路径和安装结果，不输出配置值。安装失败不得删除或截断原有安装文件。

## 文档要求

README 和 `docs/USAGE.md` 必须说明：

- 用户级安装命令与 `--force` 更新命令。
- `~/.local/bin` 的 PATH 要求。
- 安装后的稳定命令与源码仓库内 `python3 feishu-connector/scripts/...` 调用方式之间的区别。
- 安装器不会创建配置，使用者仍需按主规格配置全局 JSON、项目 JSON 或环境变量。

## 测试策略

安装器行为使用测试驱动开发，测试只写入临时 HOME 和临时 CODEX_HOME：

- 验证运行文件、入口和 Skill 的安装位置、内容与权限。
- 从与源码仓库无关的工作目录运行安装后 `feishu-notify --help`。
- 以无效 stdin 调用安装后的适配器入口，确认返回输入错误码 `2`。
- 验证相同内容可重复安装。
- 验证内容冲突默认失败且不改变原文件。
- 验证 `--force` 原子更新受管文件。
- 验证安装过程不创建或修改飞书配置文件。
- 验证安装后的 Skill 只引用稳定命令入口。
- 验证消息、引号、换行和类 Shell 文本经过命令入口后仍保持独立 argv 或 stdin 数据，不被求值。

## 验收标准

1. 全新用户目录中运行安装器后，两个稳定命令入口和 Codex Skill 均存在且可用。
2. 安装结果不依赖源码仓库继续存在，也不依赖任务当前工作目录。
3. 重复安装相同版本成功且不产生内容变化。
4. 不带 `--force` 时不会覆盖内容不同的目标文件。
5. `--force` 只替换明确的受管文件。
6. 安装过程不读取、创建、修改或输出飞书配置与 Secret。
7. 安装器及安装后的运行文件只依赖 Python 3 标准库。
