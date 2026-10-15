"""测试使用的脚本位置及文件摘要；不导入测试模块或可选渲染依赖。"""
import hashlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/tech-doc-translator/scripts'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
