"""Run the CloudyLake's Observatory development server."""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def ensure_project_interpreter() -> None:
    """Hand off to the local virtual environment when needed."""
    if importlib.util.find_spec("uvicorn") is not None:
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
        "缺少网站依赖。请先运行：\n"
        f'  "{sys.executable}" -m pip install -r "{PROJECT_ROOT / "requirements-web.txt"}"'
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local website.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind.")
    parser.add_argument(
        "--port",
        default=8765,
        type=int,
        help="Port to bind (default: 8765).",
    )
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable automatic reload after source changes.",
    )
    return parser.parse_args()


def main() -> None:
    ensure_project_interpreter()

    import uvicorn
    from dotenv import load_dotenv

    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    uvicorn.run(
        "web.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )


if __name__ == "__main__":
    main()
