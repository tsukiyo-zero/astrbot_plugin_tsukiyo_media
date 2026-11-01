"""测试基座：把仓库上一级目录加进 sys.path，之后可用包名导入。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PARENT = REPO.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

WORKFLOW_DIR = REPO / "workflows"
MODELS_JSON = REPO / "models.json"
