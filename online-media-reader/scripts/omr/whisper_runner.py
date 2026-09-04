#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""faster-whisper 转写 worker：audio_path model → stdout 输出段落 JSON。"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("model_name")
    parser.add_argument("--download-root", required=True)
    parser.add_argument("--language")
    parser.add_argument("--initial-prompt")
    args = parser.parse_args()
    from faster_whisper import WhisperModel

    download_root = Path(args.download_root).resolve()
    download_root.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(args.model_name, download_root=str(download_root))
    kwargs = {}
    if args.language:
        kwargs["language"] = args.language
    if args.initial_prompt:
        kwargs["initial_prompt"] = args.initial_prompt
    segments, _info = model.transcribe(args.audio_path, **kwargs)
    payload = [
        {"start": s.start, "end": s.end, "text": s.text} for s in segments
    ]
    json.dump(payload, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
