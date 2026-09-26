"""Cross-platform setup, requiring a user-installed Python 3.11+."""
from pathlib import Path
import subprocess
import sys
import venv

from configure_codex import configure


def main():
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=root, check=True)
    configure(root, python)
    print("Setup complete. Open and trust this repository in Codex; restart the task to discover MCP servers.")


if __name__ == "__main__":
    main()
