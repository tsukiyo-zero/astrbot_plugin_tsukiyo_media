"""从「链路模板 + 模型工作流」生成某条链路的模型专属工作流。

背景：参数与作者词只保留一份权威来源——工作流文件本身。
不同链路（自拍/参考图/编辑）结构不同，但同一个模型在这些链路上的作者词、
底模、采样参数是一样的，所以用本脚本从该模型的 text2img 工作流里取出来，
灌进链路模板，生成 `<kind>/<model_key>.json`。

用法：
    python scripts/build_chain_workflows.py --kind selfie --models obsession,miao,novaflat
    python scripts/build_chain_workflows.py --kind reference --models miao   # 之后可复用

生成的 JSON 就是最终提交给 ComfyUI 的东西（除人设词/用户描述/种子/参考图外），
改参数请改这里，或改完后用 ComfyUI 导出覆盖同名文件。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_node(workflow: dict[str, Any], class_type: str) -> tuple[str, dict[str, Any]]:
    hits = [(nid, node) for nid, node in workflow.items() if node.get("class_type") == class_type]
    if len(hits) != 1:
        raise SystemExit(f"期望恰好一个 {class_type} 节点，实际 {len(hits)} 个")
    return hits[0]


def model_catalog() -> dict[str, dict[str, Any]]:
    data = load_json(ROOT / "models.json")
    return data.get("models", {})


def build(kind: str, models: list[str]) -> None:
    template_path = WORKFLOWS / kind / "default.json"
    if not template_path.exists():
        raise SystemExit(f"找不到链路模板：{template_path}")
    catalog = model_catalog()

    for key in models:
        entry = catalog.get(key)
        if not entry:
            raise SystemExit(f"models.json 里没有模型：{key}")
        draw_path = WORKFLOWS / str(entry["workflow"])
        if not draw_path.exists():
            raise SystemExit(f"模型「{key}」的工作流不存在：{draw_path}")

        template = load_json(template_path)
        source = load_json(draw_path)

        _, load_node = find_node(source, "CheckpointLoaderSimple")
        _, sampler_node = find_node(source, "KSampler")
        pos_id = sampler_node["inputs"]["positive"][0]
        neg_id = sampler_node["inputs"]["negative"][0]
        pos_text = source[pos_id]["inputs"]["text"]
        neg_text = source[neg_id]["inputs"]["text"]

        tpl_load_id, _ = find_node(template, "CheckpointLoaderSimple")
        tpl_sampler_id, tpl_sampler = find_node(template, "KSampler")
        tpl_pos_id = tpl_sampler["inputs"]["positive"][0]
        tpl_neg_id = tpl_sampler["inputs"]["negative"][0]

        template[tpl_load_id]["inputs"]["ckpt_name"] = load_node["inputs"]["ckpt_name"]
        template[tpl_pos_id]["inputs"]["text"] = pos_text
        template[tpl_neg_id]["inputs"]["text"] = neg_text
        for field in ("steps", "cfg", "sampler_name", "scheduler"):
            if field in sampler_node["inputs"]:
                template[tpl_sampler_id]["inputs"][field] = sampler_node["inputs"][field]

        out = WORKFLOWS / kind / f"{key}.json"
        save_json(out, template)
        print(f"已生成 {out.relative_to(ROOT)}  ← 底模 {load_node['inputs']['ckpt_name']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成链路专属工作流")
    parser.add_argument("--kind", required=True, choices=["selfie", "reference", "edit"])
    parser.add_argument("--models", required=True, help="逗号分隔的模型 key")
    args = parser.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    build(args.kind, models)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
