# 飞书连接器 Skill 安装器设计

## 目标

安装器仅将自包含的 `feishu-notify` Skill 安装到用户的 Codex Skill 目录，使已安装入口不依赖源码仓库位置或当前工作目录。消息、配置与错误行为以 [当前契约](feishu-connector.md) 为准。

## 范围与位置

运行 `python3 feishu-connector/install_skill.py`；更新冲突的受管文件时运行 `python3 feishu-connector/install_skill.py --force`。源目录为 `feishu-connector/skills/feishu-notify`，目标目录为 `${CODEX_HOME:-~/.codex}/skills/feishu-notify`。

安装器不支持 Windows，不安装 launcher 或通用 package，不修改 Shell 配置，不创建卸载器，也不创建、读取或修改飞书配置、Secret、Token 或 Open ID。

## 固定 manifest

安装器只管理以下六个文件及其目标权限：

| 相对路径 | 权限 |
| --- | --- |
| `SKILL.md` | `0644` |
| `scripts/feishu_notify.py` | `0755` |
| `scripts/feishu_connector/__init__.py` | `0644` |
| `scripts/feishu_connector/client.py` | `0644` |
| `scripts/feishu_connector/config.py` | `0644` |
| `scripts/feishu_connector/cli.py` | `0644` |

每个源文件必须是普通文件。安装器创建缺失目录，并以同目录临时文件写入、设置权限、原子替换和最终校验完成发布。

## 更新、`--force` 与未知文件

内容和权限均与 manifest 相同的受管文件视为已安装，重复运行成功且不改动它。受管文件缺失时会创建；现有受管文件的内容或权限不一致时，默认失败且保留原文件。只有 `--force` 才替换这些冲突的受管文件。

目标 Skill 目录中不在 manifest 内的文件不是安装器管理对象，始终保留。安装器不会递归删除目标目录、清理未知文件或自动删除旧版 `~/.local` 布局；如旧版文件不再需要，由用户确认后一次性手动清理。

## 安全边界

威胁模型是普通单用户本地使用：安装器避免日常误覆盖与部分写入，但不承诺抵御同一用户下恶意进程在安装窗口内篡改目录、硬链接或临时文件。该边界不要求目录描述符链、inode 身份验证、`ctypes` 调用或失败恢复路径。

安装结果只报告受管 Skill 文件与错误；不会输出配置值或秘密。失败不得截断或删除原有受管文件。

## 验收标准

1. 在全新 `CODEX_HOME` 中安装后，六个 manifest 文件存在、内容一致且权限正确。
2. 已安装入口 `${CODEX_HOME:-~/.codex}/skills/feishu-notify/scripts/feishu_notify.py` 可在源码仓库移除后运行。
3. 相同版本可重复安装；冲突默认失败；`--force` 仅替换 manifest 中的冲突文件。
4. 未知文件、飞书配置与旧版用户目录文件均不被安装器删除或修改。
5. 安装器与安装后的 Skill 只依赖 Python 标准库。
