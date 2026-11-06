import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"


def ensure_venv() -> None:
    if Path(sys.prefix).resolve() == VENV.resolve():
        return
    if not VENV_PYTHON.exists():
        sys.exit("Backend environment missing. Run: cd backend && uv sync")
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(ROOT / "main.py"), *sys.argv[1:]])


def run() -> None:
    import uvicorn

    os.chdir(ROOT)
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8100"))
    reload = "--no-reload" not in sys.argv
    uvicorn.run("app.main:app", host=host, port=port, reload=reload, reload_dirs=[str(ROOT / "app")])


if __name__ == "__main__":
    ensure_venv()
    run()
