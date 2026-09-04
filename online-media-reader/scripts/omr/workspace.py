# -*- coding: utf-8 -*-
"""一次读取的固定目录、运行清单与原子结果交付。"""

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .model import ReviewState, WorkspaceFinalizationError


def content_id_from_url(platform, url):
    """从规范 URL 提取不含标题的内容 ID，无法提取时使用稳定匿名标识。"""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    patterns = {
        "douyin": r"/video/([^/?#]+)",
        "bilibili": r"/video/([^/?#]+)",
        "xiaohongshu": r"/(?:explore|discovery/item)/([^/?#]+)",
    }
    match = re.search(patterns.get(platform, r"$^"), parsed.path)
    value = match.group(1) if match else ""
    if platform == "douyin" and not value:
        value = (query.get("modal_id") or [""])[0]
    value = re.sub(r"[^0-9A-Za-z._-]", "-", value).strip("-.")
    if value:
        return value
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return f"unknown-{digest}"


def _available_path(parent, basename):
    candidate = parent / basename
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{basename}-{suffix}"
        suffix += 1
    return candidate


def write_json_atomic(path, payload):
    """JSON 落盘统一走 .part 暂存后原子替换。"""
    part = path.with_name(path.name + ".part")
    try:
        part.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


@dataclass
class RunWorkspace:
    media_root: Path
    platform: str
    input_url: str
    timestamp: str
    run_dir: Path
    output_override: Optional[Path] = None
    canonical_url: str = ""
    content_id: str = "unknown"
    status: str = "running"
    stage: str = "initializing"
    processing_path: str = ""
    review: ReviewState = ReviewState()
    error: Optional[str] = None

    @classmethod
    def create(cls, cwd, platform, input_url, output=None):
        media_root = (Path(cwd) / ".media").resolve()
        media_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        run_dir = _available_path(media_root, f"{platform}-unknown-{timestamp}")
        run_dir.mkdir()
        (run_dir / "work").mkdir()
        output_override = None
        if output:
            raw_output = Path(output)
            output_override = (
                raw_output if raw_output.is_absolute() else Path(cwd) / raw_output
            ).resolve()
        workspace = cls(
            media_root=media_root,
            platform=platform,
            input_url=input_url,
            timestamp=timestamp,
            run_dir=run_dir,
            output_override=output_override,
        )
        workspace.write_manifest()
        return workspace

    @classmethod
    def load(cls, run_dir):
        """从既有 manifest.json 恢复运行状态，供复核入口续用交付边界。"""
        run_dir = Path(run_dir).resolve()
        state = json.loads(
            (run_dir / "manifest.json").read_text(encoding="utf-8")
        )
        result_path = Path(state["result_path"])
        output_override = (
            result_path if result_path.resolve() != (run_dir / "content.md") else None
        )
        workspace = cls(
            media_root=run_dir.parent,
            platform=state["platform"],
            input_url=state["input_url"],
            timestamp="",
            run_dir=run_dir,
            output_override=output_override,
            canonical_url=state.get("canonical_url", ""),
            content_id=state.get("content_id", "unknown"),
            status=state.get("status", "running"),
            stage=state.get("stage", ""),
            processing_path=state.get("processing_path", ""),
            review=ReviewState.from_dict(state),
            error=state.get("error"),
        )
        corrections_file = run_dir / "review" / "corrections.json"
        interrupted_review_cleanup = (
            workspace.status == "success"
            and workspace.stage == "complete"
            and workspace.review.status in {"reviewed", "unavailable"}
            and workspace.review.path
            and workspace.work_dir.exists()
            and corrections_file.is_file()
        )
        if interrupted_review_cleanup:
            workspace.status = "error"
            workspace.stage = "cleanup"
            workspace.error = "检测到上次复核在工作目录清理完成前中断。"
            workspace.review = ReviewState.pending(workspace.review.path)
        return workspace

    @property
    def work_dir(self):
        return self.run_dir / "work"

    @property
    def artifacts_dir(self):
        return self.run_dir / "artifacts"

    @property
    def result_path(self):
        return self.output_override or (self.run_dir / "content.md")

    @property
    def manifest_path(self):
        return self.run_dir / "manifest.json"

    def bind_manifest(self, manifest):
        """取得规范 URL 后确定最终目录名，并修正目录内 Cookie 路径。"""
        self.canonical_url = manifest.canonical_url
        self.content_id = content_id_from_url(self.platform, manifest.canonical_url)
        old_dir = self.run_dir
        basename = f"{self.platform}-{self.content_id}-{self.timestamp}"
        target = _available_path(self.media_root, basename)
        old_cookie = Path(manifest.cookie_file) if manifest.cookie_file else None
        old_dir.rename(target)
        self.run_dir = target
        if old_cookie:
            try:
                relative_cookie = old_cookie.relative_to(old_dir)
            except ValueError:
                pass
            else:
                manifest.cookie_file = str(target / relative_cookie)
        self.write_manifest(manifest)

    def set_stage(self, stage, manifest=None):
        self.stage = stage
        self.write_manifest(manifest)

    def deliver(self, markdown):
        destination = self.result_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = (
            self.work_dir / "content.md.part"
            if self.output_override is None
            else destination.with_name(destination.name + ".part")
        )
        try:
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_text(markdown, encoding="utf-8")
            part.replace(destination)
        finally:
            part.unlink(missing_ok=True)

    def complete(self, manifest):
        self.cleanup_cookies(manifest)
        self.status = "success"
        self.stage = "complete"
        self.error = None
        self.write_manifest(manifest)
        if self.work_dir.exists():
            try:
                shutil.rmtree(self.work_dir)
            except (OSError, KeyboardInterrupt) as exc:
                self.status = "error"
                self.stage = "cleanup"
                detail = "用户中断" if isinstance(exc, KeyboardInterrupt) else str(exc)
                self.error = f"工作目录清理失败：{detail}"
                if (
                    self.review.status in {"reviewed", "unavailable"}
                    and self.review.path
                ):
                    self.review = ReviewState.pending(self.review.path)
                try:
                    self.write_manifest()
                except OSError as state_error:
                    self.error = f"{self.error}；运行清单写入失败：{state_error}"
                if isinstance(exc, KeyboardInterrupt):
                    raise
                raise WorkspaceFinalizationError(self.error) from exc

    def fail(self, error, manifest=None):
        self.cleanup_cookies(manifest)
        self.status = "error"
        self.error = str(error)
        self.write_manifest(manifest)

    def start_review_attempt(self):
        """开始一次复核尝试；只重置内存态，持久状态由成功或失败出口更新。"""
        self.status = "running"
        self.stage = "reviewing"
        self.error = None

    def record_review_failure(self, error, stage):
        """记录当前复核失败；已完成终态不改写，已记录的同一失败直接复用。"""
        try:
            durable = type(self).load(self.run_dir)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None
        same_recorded_failure = (
            durable.status == "error"
            and self.status == "error"
            and durable.stage == self.stage
            and durable.error == self.error
        )
        if same_recorded_failure:
            return durable.failure_payload()
        if not durable.review.required:
            return None
        durable.stage = stage
        durable.fail(error)
        return durable.failure_payload()

    def cleanup_cookies(self, manifest=None):
        if manifest is not None and manifest.cookie_file:
            Path(manifest.cookie_file).unlink(missing_ok=True)
            manifest.cookie_file = None
        if self.work_dir.exists():
            for path in self.work_dir.rglob("cookies.txt"):
                path.unlink(missing_ok=True)

    def artifact_paths(self):
        if not self.artifacts_dir.exists():
            return []
        return [
            str(path.resolve())
            for path in sorted(self.artifacts_dir.rglob("*"))
            if path.is_file()
        ]

    def state_payload(self):
        payload = {
            "input_url": self.input_url,
            "canonical_url": self.canonical_url,
            "platform": self.platform,
            "content_id": self.content_id,
            "status": self.status,
            "stage": self.stage,
            "processing_path": self.processing_path,
            "result_path": str(self.result_path),
            "artifact_paths": self.artifact_paths(),
        }
        payload.update(self.review.to_dict())
        if self.error is not None:
            payload["error"] = self.error
        return payload

    def success_payload(self):
        payload = {
            "status": "success",
            "stage": self.stage,
            "result_path": str(self.result_path),
            "processing_path": self.processing_path,
            "review_required": self.review.required,
            "run_dir": str(self.run_dir),
        }
        payload.update(self.review.to_dict())
        return payload

    def failure_payload(self):
        return {
            "status": "error",
            "stage": self.stage,
            "error": self.error,
            "run_dir": str(self.run_dir),
        }

    def write_manifest(self, manifest=None):
        if manifest is not None:
            self.canonical_url = manifest.canonical_url
            self.processing_path = manifest.processing_path
            self.review = manifest.review
        write_json_atomic(self.manifest_path, self.state_payload())
