"""Run the automatic sounding collector and quicklook renderer."""

import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def ensure_project_interpreter() -> None:
    if (
        importlib.util.find_spec("metpy") is not None
        and importlib.util.find_spec("httpx") is not None
    ):
        return

    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    current_python = Path(sys.executable).resolve()
    if venv_python.exists() and current_python != venv_python.resolve():
        completed = subprocess.run(
            [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
            check=False,
        )
        raise SystemExit(completed.returncode)

    raise SystemExit(
        "缺少采集与绘图依赖。请先运行：\n"
        f'  "{sys.executable}" -m pip install -r "{PROJECT_ROOT / "requirements-web.txt"}"'
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect, archive and render sounding observations."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "sounding_collector.json",
        help="Collector JSON configuration.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one collection pass and exit.",
    )
    return parser.parse_args()


async def run() -> None:
    ensure_project_interpreter()

    from meteostation.sounding.collector import (
        SoundingCollector,
        load_collector_config,
    )

    args = parse_args()
    config = load_collector_config(args.config)
    collector = SoundingCollector(
        config=config,
        raw_data_root=PROJECT_ROOT / "data" / "raw",
        product_root=PROJECT_ROOT / "data" / "products",
        state_path=PROJECT_ROOT / "data" / "state" / "sounding_collector.json",
        font_path=PROJECT_ROOT / "MiSans VF.ttf",
    )

    if args.once:
        summary = await collector.run_once()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    print(
        "探空采集器已启动："
        f"每 {config.poll_interval_seconds} 秒检查一次，按 Ctrl+C 停止。"
    )
    await collector.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("探空采集器已停止。")
