import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PDDLSTREAM_DIR = REPO_ROOT / "external" / "pddlstream"
DOWNWARD_DIR = PDDLSTREAM_DIR / "downward"


def run(command: list[str], cwd: Path | None = None) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    if not (REPO_ROOT / ".git").exists():
        raise RuntimeError(f"Repository root not found: {REPO_ROOT}")

    run(["git", "submodule", "update", "--init", "external/pddlstream"], cwd=REPO_ROOT)

    if not PDDLSTREAM_DIR.exists():
        raise FileNotFoundError(f"PDDLStream submodule is missing at {PDDLSTREAM_DIR}")

    run(["git", "submodule", "update", "--init", "--recursive"], cwd=PDDLSTREAM_DIR)

    if not DOWNWARD_DIR.exists():
        raise FileNotFoundError(f"Fast Downward checkout is missing at {DOWNWARD_DIR}")

    build_dir = DOWNWARD_DIR / "builds"
    if not build_dir.exists() or not any(build_dir.iterdir()):
        run([sys.executable, "build.py"], cwd=DOWNWARD_DIR)
    else:
        print(f"Fast Downward already appears to be built at {build_dir}")

    print("PDDLStream setup complete.")


if __name__ == "__main__":
    main()
