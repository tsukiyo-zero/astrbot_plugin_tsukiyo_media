"""真机冒烟测试：真的向 ComfyUI 提交一张图，验证 连接 → 绑定 → 取图 → 落盘 全链路。

用法（需要能访问 ComfyUI 的环境，且已安装 httpx）：
    python scripts/smoke.py --base-url http://127.0.0.1:8188 --prompt "a cat on a roof"
    python scripts/smoke.py --kind selfie --reference /path/to/normal.png --prompt "sitting on bed"

不依赖 AstrBot，可在容器里或本机独立运行。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from astrbot_plugin_tsukiyo_media.backends.comfyui.client import ComfyUIClient  # noqa: E402
from astrbot_plugin_tsukiyo_media.core.catalog import ModelCatalog  # noqa: E402
from astrbot_plugin_tsukiyo_media.core.pipeline import (  # noqa: E402
    ImagePipeline,
    KindProfile,
    PipelineSettings,
)
from astrbot_plugin_tsukiyo_media.core.types import (  # noqa: E402
    KIND_EDIT,
    KIND_REFERENCE,
    KIND_SELFIE,
    ImageRequest,
    normalize_kind,
)


def build_profiles(reference: str) -> dict[str, KindProfile]:
    return {
        KIND_SELFIE: KindProfile(
            workflow="selfie-ref.json",
            identity_prompt="1girl, solo, adult, mature female, blue hair, long hair, gradient hair, blue eyes, fish fin ears, whale tail",
            identity_image=reference,
            ipadapter_weight=0.45,
            fixed_prompt="cowboy shot, upper body, detailed face",
            width=832,
            height=1216,
        ),
        KIND_REFERENCE: KindProfile(
            workflow="reference-ref.json",
            ipadapter_weight=0.55,
            width=1024,
            height=1536,
        ),
        KIND_EDIT: KindProfile(
            workflow="edit-img2img.json",
            denoise=0.55,
        ),
    }


async def run(args: argparse.Namespace) -> int:
    kind = normalize_kind(args.kind)
    client = ComfyUIClient(
        args.base_url,
        connect_timeout=10,
        job_timeout=args.timeout,
        poll_interval=1.0,
    )
    catalog = ModelCatalog(ROOT / "models.json")
    settings = PipelineSettings(
        negative_prompt="worst quality, low quality, watermark, text",
        prompt_mode="append",
        job_timeout=args.timeout,
        profiles=build_profiles(args.reference or ""),
    )
    pipeline = ImagePipeline(
        client=client,
        catalog=catalog,
        settings=settings,
        workflow_dir=ROOT / "workflows",
        output_dir=Path(args.output or (ROOT / "output")),
    )
    request = ImageRequest(
        prompt=args.prompt,
        kind=kind,
        model_key=args.model,
        references=[args.reference] if args.reference else [],
        seed=args.seed,
        source="smoke",
    )
    try:
        result = await pipeline.generate(request)
    finally:
        await client.close()

    print(json.dumps(result.to_receipt(), ensure_ascii=False, indent=2))
    if result.ok and result.paths:
        for path in result.paths:
            print(f"saved: {path} ({Path(path).stat().st_size} bytes)")
    print("--- positive ---")
    print(result.positive[:600])
    print("--- negative ---")
    print(result.negative[:300])
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="tsukiyo_media 冒烟测试")
    parser.add_argument("--base-url", default="http://127.0.0.1:8188")
    parser.add_argument("--prompt", default="a cat sleeping on a tiled roof, warm afternoon light")
    parser.add_argument("--kind", default="text2img")
    parser.add_argument("--model", default="")
    parser.add_argument("--reference", default="")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", default="")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
