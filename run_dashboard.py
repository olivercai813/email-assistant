"""Launch the Streamlit dashboard."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).resolve().parent
    dashboard_script = project_root / "app" / "dashboard" / "streamlit_app.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_script),
            "--server.headless=true",
        ],
        cwd=str(project_root),
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
