import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PDDLSTREAM_DIR = REPO_ROOT / "external" / "pddlstream"
DOWNWARD_DIR = PDDLSTREAM_DIR / "downward"


def run(command: list[str], cwd: Path | None = None) -> None:
    print(f"+ {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def ensure_downward_release_build() -> None:
    translate_dir = DOWNWARD_DIR / "builds" / "release" / "bin" / "translate"
    if translate_dir.exists():
        print(f"Fast Downward already appears to be built at {translate_dir}")
        return

    try:
        run([sys.executable, "build.py"], cwd=DOWNWARD_DIR)
    except subprocess.CalledProcessError:
        build_downward_with_cmake_policy()


def build_downward_with_cmake_policy() -> None:
    cmake = shutil.which("cmake")
    if not cmake:
        raise FileNotFoundError("cmake was not found while building Fast Downward.")

    build_dir = DOWNWARD_DIR / "builds" / "release"
    build_dir.mkdir(parents=True, exist_ok=True)

    run(
        [
            cmake,
            "-G",
            "Unix Makefiles",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            "../../src",
        ],
        cwd=build_dir,
    )
    run([cmake, "--build", "."], cwd=build_dir)


def main() -> None:
    if not (REPO_ROOT / ".git").exists():
        raise RuntimeError(f"Repository root not found: {REPO_ROOT}")

    run(["git", "submodule", "update", "--init", "external/pddlstream"], cwd=REPO_ROOT)

    if not PDDLSTREAM_DIR.exists():
        raise FileNotFoundError(f"PDDLStream submodule is missing at {PDDLSTREAM_DIR}")

    run(["git", "submodule", "update", "--init", "--recursive"], cwd=PDDLSTREAM_DIR)

    if not DOWNWARD_DIR.exists():
        raise FileNotFoundError(f"Fast Downward checkout is missing at {DOWNWARD_DIR}")

    ensure_downward_release_build()

    print("PDDLStream setup complete.")


if __name__ == "__main__":
    main()
