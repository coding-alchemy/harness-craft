---
name: feishu-notify
description: Use when users ask to send a plain-text Feishu message or when configured task-completion notification applies.
---

# Feishu Notify

Use the installed `feishu-notify` CLI. Do not implement Feishu HTTP requests in this Skill, do not read or print App Secret or access tokens, and do not send messages unless one of the workflows below applies.

The CLI resolves Phase 2 configuration itself using process environment, project JSON, and global JSON. This Skill must not open either JSON file, inspect the legacy `.env`, choose a recipient, or reproduce merge and secret rules. Repository instructions may supply `--project-root` only when they explicitly need to override Git/current-directory discovery; otherwise preserve the existing argv prefixes.

## argv safety

Every dynamic value, including user text and task-derived fields, must be passed as an independent, literal argv parameter and must not be handed to shell parsing. Use an argv-capable execution tool with shell execution disabled. Never assemble a shell command from dynamic text or use command substitution, variable expansion, interpolated quotes, or any other shell evaluation to supply a value.

## Shell-only execution fallback

If the available command facility accepts only a shell command string, use this fallback only when it also provides a separate stdin/input-data channel. Do not put any message or task value in the shell string. Send one of these JSON objects as the separate input data:

```json
{"flow": "send", "message": "the exact user-designated text"}
```

```json
{"flow": "task-auto", "status": "success", "task": "short task name", "summary": "short outcome", "repo": "repository name", "branch": "branch name"}
```

Invoke this static shell string, with no dynamic values in it:

```sh
feishu-notify-adapter
```

The adapter reads exactly one JSON object from standard input, maps `send` to the same `feishu-notify send --message` contract and `task-auto` to the same `feishu-notify task --auto` contract, invokes the CLI with an argv list and shell execution disabled, and propagates the CLI result and exit code exactly. It is only an adapter: do not add HTTP calls, token or secret reading/printing, or other connector logic.

If the tool cannot provide separate stdin data, this fallback is prohibited; use an argv-capable tool instead. For automatic notification, capture the result as a secondary notification outcome: a notification failure may add one redacted warning but must not change the original task result.

## Explicit message workflow

When the user explicitly asks to send text to Feishu:

1. Use exactly the text the user designated for sending. Do not attach source code, logs, Diff, or other context unless the user explicitly included it.
2. Invoke the fixed argv prefix `feishu-notify send --message`, followed by the exact user-designated text as one independent, literal argv parameter. This notation is an argv sequence, not a shell command.

3. Report whether the CLI succeeded. If it failed, report the CLI's redacted warning without exposing configuration values.

This workflow does not depend on `FEISHU_AUTO_NOTIFY`.

## Automatic task-completion workflow

Use this workflow only when repository instructions enable it and the current task is about to return its final result. Run it at most once per final task result.

1. Derive:
   - `status`: `success` only when the original task succeeded; otherwise `failure`.
   - `task`: a short name based on the user's request.
   - `summary`: one short outcome summary. Never send the 完整最终回复、完整日志、Diff、内部推理, secrets, tokens, or unrelated context.
   - `repo`: the current Git repository directory name, or the current directory name outside Git.
   - `branch`: `git branch --show-current`; use `detached` if it is empty.
2. Invoke the CLI's safe configuration gate with the fixed argv prefix `feishu-notify task --auto`, then pass each option and its value as separate literal argv parameters: `--status` with `success` or `failure`, followed by `--task`, `--summary`, `--repo`, and `--branch` with their respective derived values. This notation is an argv sequence, not a shell command.
3. If the command reports that automatic notification is disabled, do not send anything and do not mention an error.
4. If sending fails, append one short redacted warning to the original final response. 通知失败不得改变原任务结果，也不得覆盖原失败原因或 trigger another work cycle.
