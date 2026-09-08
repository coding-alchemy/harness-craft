# -*- coding: utf-8 -*-
"""测试共享夹具：运行暂存使用持久输出根内的独立工作子目录。

产品在普通运行时拒绝系统临时根下的输出位置（见 gallery-and-durable-evidence
设计第 3.2 节），因此涉及运行目录/入口子进程的测试改用仓库 `.media` 下的
一次性工作根；每条测试独立子目录，结束即清理。
"""

import os
import uuid
from pathlib import Path

import pytest

TEST_MEDIA_ROOT = Path(__file__).resolve().parents[2] / ".media" / "omr-test"

# 部分测试会把 os.open、shutil.rmtree、subprocess.run 替换为桩；清理统一用
# 导入时保存的真实 subprocess.run 引用，与进程内任何补丁隔离。
import subprocess as _subprocess_module

_real_run = _subprocess_module.run


@pytest.fixture
def work_root():
    root = TEST_MEDIA_ROOT / f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        _real_run(["rm", "-rf", str(root)], check=False)
