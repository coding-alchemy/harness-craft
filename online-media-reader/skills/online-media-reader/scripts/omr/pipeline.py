# -*- coding: utf-8 -*-
"""处理决策：字幕优先，按需下载转写，--keep-media 只保留媒体。

就地更新传入的 manifest（设置 subtitle_tracks 顺序、processing_path、media 落盘路径）。
"""

import re
from pathlib import Path
from urllib.parse import urlparse

from . import browser_session, media, review
from .model import ContentManifest, ReviewState
from .subtitles import assess_track, choose_track, track_from_asr_segments

ASR_LABEL = "语音转写（ASR）"


def process(manifest: ContentManifest, workdir: Path, artifacts_dir: Path,
            keep_media=False, verify_audio=False, whisper_model="small"):
    """按设计决策顺序填充文字来源；需要保留的媒体写入 artifacts。"""
    if manifest.content_type == "image_gallery":
        from . import ocr as ocr_module

        images_dir = workdir / "images"
        images_dir.mkdir(exist_ok=True)
        for image in manifest.image_items:
            if image.ocr_text is None:
                suffix = Path(urlparse(image.url).path).suffix
                suffix = suffix if re.fullmatch(r"\.[0-9A-Za-z]{1,8}", suffix) else ".img"
                dest = images_dir / f"{image.index:03d}{suffix}"
                media.download_image(image.url, dest)
                image.ocr_text = ocr_module.ocr_image(
                    dest,
                    workdir / "ocr",
                    workdir.parent.parent / "tools" / "paddleocr",
                )
        if any(i.ocr_text for i in manifest.image_items):
            manifest.processing_path = "图片 OCR"
        else:
            manifest.processing_path = "未获得文字（OCR 无结果）"
        return manifest

    track = choose_track(manifest.subtitle_tracks)
    reliable = False
    if track is not None:
        reliable, _issues = assess_track(track, manifest.duration)
    # 可靠字幕默认不转写；--verify-audio 显式要求时例外
    if track is not None and reliable and not verify_audio:
        manifest.subtitle_tracks = [track]
        manifest.processing_path = track.label()
        if keep_media:
            _ensure_media_access(manifest, workdir)
            _download_keep_copy(manifest, artifacts_dir, workdir)
            _delete_cookie(manifest)
        return manifest

    # 字幕缺失、不可靠或要求原音核验：下载并转写
    _ensure_media_access(manifest, workdir)
    media_dest = workdir / "source.m4a"
    _acquire_audio(manifest, media_dest, workdir)
    if keep_media:
        _download_keep_copy(manifest, artifacts_dir, workdir)
    audio_path = workdir / "audio.wav"
    media.extract_audio(media_dest, audio_path)
    language, initial_prompt = _transcription_context(manifest)
    segments = media.transcribe_audio(
        audio_path,
        whisper_model,
        language=language,
        initial_prompt=initial_prompt,
        download_root=workdir.parent.parent / "tools" / "faster-whisper",
    )
    asr_track = track_from_asr_segments(segments)
    if asr_track.cues:
        if track is not None and reliable:
            manifest.subtitle_tracks = [track, asr_track]
            manifest.processing_path = f"{track.label()} + 原音核验（ASR）"
        else:
            manifest.subtitle_tracks = (
                [asr_track, track] if track is not None else [asr_track]
            )
            manifest.processing_path = ASR_LABEL
            _prepare_review_evidence(manifest, workdir, artifacts_dir)
    else:
        manifest.subtitle_tracks = [track] if track is not None else []
        manifest.processing_path = (
            f"{track.label()}（原音核验无结果）"
            if track is not None and reliable
            else "未获得文字（转写无结果）"
        )
    # 复核视频属于最后的媒体定位需求，全部取得后才删除匿名 Cookie
    _delete_cookie(manifest)
    return manifest


def _prepare_review_evidence(manifest, workdir, artifacts_dir):
    """ASR 为主文字源时准备画面证据；失败只降级复核，不放弃转写结果。"""
    try:
        review.prepare(manifest, workdir.parent, workdir, artifacts_dir)
    except Exception as exc:
        manifest.review = ReviewState.unavailable(exc)


def _ensure_media_access(manifest, workdir):
    """抖音只在确定需要媒体时创建匿名会话。"""
    sources = manifest.media_sources
    has_direct_media = bool(sources.audio or sources.muxed)
    if (
        manifest.platform == "douyin"
        and not manifest.cookie_file
        and not has_direct_media
    ):
        cookie = browser_session.anonymous_cookie_jar(manifest.canonical_url, workdir)
        manifest.cookie_file = str(cookie)


def _acquire_audio(manifest, dest, workdir):
    """取得转写用音频：优先经页面验证的直连地址，否则 yt-dlp。"""
    sources = manifest.media_sources
    if sources.audio:
        media.download_direct(sources.audio, dest, referer=sources.referer)
    else:
        media.download_media(
            manifest.canonical_url, dest, mode="audio", cookies=manifest.cookie_file
        )


def _download_keep_copy(manifest, artifacts_dir: Path, workdir: Path):
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dest = artifacts_dir / "source.mp4"
    # 保留容器后缀，让 ffmpeg 和 yt-dlp 都能确定输出格式；work/ 本身是发布前暂存区。
    staging = workdir / "source.mp4"
    sources = manifest.media_sources
    try:
        if sources.video and sources.audio:
            video_tmp = workdir / "video.m4s"
            audio_tmp = workdir / "keep-audio.m4s"
            media.download_direct(
                sources.video, video_tmp, referer=sources.referer
            )
            media.download_direct(
                sources.audio, audio_tmp, referer=sources.referer
            )
            media.mux_av(video_tmp, audio_tmp, staging)
        elif sources.muxed:
            # 合成流（抖音 playwm）：音视频一体，先落到运行工作区。
            media.download_direct(sources.muxed, staging, referer=sources.referer)
        else:
            media.download_media(
                manifest.canonical_url,
                staging,
                mode="best",
                cookies=manifest.cookie_file,
            )
        staging.replace(dest)
        manifest.media_items = [{"path": str(dest)}]
    finally:
        staging.unlink(missing_ok=True)
        media.cleanup_download_parts(staging)


def _transcription_context(manifest):
    values = []
    if manifest.title:
        values.append(f"标题：{' '.join(manifest.title.split())}")
    if manifest.author:
        values.append(f"作者：{' '.join(manifest.author.split())}")
    context = "；".join(values)[:240]
    if not re.search(r"[\u3400-\u9fff]", context):
        return None, None
    return "zh", context


def _delete_cookie(manifest):
    """匿名 Cookie 在媒体定位完成后尽早删除，不等临时目录清理。"""
    if manifest.cookie_file:
        Path(manifest.cookie_file).unlink(missing_ok=True)
        manifest.cookie_file = None
