import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REL_TOLERANCE = 5e-3
ABS_TOLERANCE = 1e-3


def evaluate_task_result(
        project_root: str,
        domain: str,
        instance_name: str,
        task_item: dict[str, Any],
        pddlstream_dir: str,
    ) -> dict[str, Any]:
    result_dir = Path(project_root) / "results" / domain / instance_name
    evaluation_path = result_dir / "evaluation.json"

    evaluation: dict[str, Any] = {
        "instance_name": instance_name,
        "result_dir": str(result_dir),
        "pddlstream_dir": str(Path(pddlstream_dir)),
        "predicted_answer": None,
        "expected_answer": None,
        "correct": None,
        "error": None,
    }

    try:
        repo_dir = require_pddlstream_repo(Path(pddlstream_dir))
        run_info = run_generated_program(result_dir, repo_dir)
        evaluation.update(run_info)

        result_json_path = result_dir / "result.json"
        if not result_json_path.exists():
            raise FileNotFoundError(f"PDDLStream did not produce result.json in {result_dir}")

        with open(result_json_path, "r", encoding="utf-8") as f:
            result_payload = json.load(f)

        predicted = extract_first_numeric(result_payload.get("answer"))
        expected = extract_expected_answer(task_item)
        evaluation["predicted_answer"] = predicted
        evaluation["expected_answer"] = expected
        evaluation["raw_result"] = result_payload

        if predicted is not None and expected is not None:
            evaluation["correct"] = math.isclose(
                predicted,
                expected,
                rel_tol=REL_TOLERANCE,
                abs_tol=ABS_TOLERANCE,
            )
        else:
            evaluation["correct"] = None
    except Exception as exc:
        evaluation["error"] = str(exc)

    with open(evaluation_path, "w", encoding="utf-8") as f:
        json.dump(evaluation, f, ensure_ascii=False, indent=2)
    return evaluation


def require_pddlstream_repo(repo_dir: Path) -> Path:
    if not repo_dir.exists():
        raise FileNotFoundError(
            f"PDDLStream repository not found at {repo_dir}. "
            "Clone it there before running evaluation."
        )
    if not (repo_dir / "pddlstream").exists():
        raise FileNotFoundError(
            f"Directory {repo_dir} does not look like a PDDLStream checkout."
        )
    ensure_downward_build(repo_dir)
    return repo_dir


def ensure_downward_build(repo_dir: Path) -> None:
    downward_dir = repo_dir / "downward"
    try:
        get_downward_translate_path(repo_dir)
        return
    except FileNotFoundError:
        pass

    try:
        subprocess.run(
            [sys.executable, "build.py"],
            cwd=downward_dir,
            check=True,
        )
    except subprocess.CalledProcessError:
        build_downward_with_cmake_policy(downward_dir)

    get_downward_translate_path(repo_dir)


def run_generated_program(result_dir: Path, repo_dir: Path) -> dict[str, Any]:
    env = os.environ.copy()
    pythonpath_entries = [
        str(get_downward_translate_path(repo_dir)),
        str(repo_dir),
    ]
    if env.get("PYTHONPATH"):
        pythonpath_entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

    completed = subprocess.run(
        [sys.executable, "run.py"],
        cwd=result_dir,
        capture_output=True,
        text=True,
        env=env,
    )

    stdout_path = result_dir / "pddlstream_stdout.log"
    stderr_path = result_dir / "pddlstream_stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    return {
        "pddlstream_returncode": completed.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }


def get_downward_translate_path(repo_dir: Path) -> Path:
    downward_dir = repo_dir / "downward" / "builds"
    for release_name in ("release", "release64", "release32"):
        candidate = downward_dir / release_name / "bin" / "translate"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Could not find Fast Downward translate directory under {downward_dir}. "
        "Run scripts/setup_pddlstream.py first."
    )


def build_downward_with_cmake_policy(downward_dir: Path) -> None:
    cmake = shutil.which("cmake")
    if not cmake:
        raise FileNotFoundError("cmake was not found while building Fast Downward.")

    build_dir = downward_dir / "builds" / "release"
    build_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            cmake,
            "-G",
            "Unix Makefiles",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            "../../src",
        ],
        cwd=build_dir,
        check=True,
    )
    subprocess.run(
        [cmake, "--build", "."],
        cwd=build_dir,
        check=True,
    )


def extract_expected_answer(task_item: dict[str, Any]) -> float | None:
    for key in ("answer_number", "answer", "answer_latex"):
        if key in task_item:
            value = extract_first_numeric(task_item[key])
            if value is not None:
                return value

    candidates = []
    collect_answer_candidates(task_item, candidates)
    for candidate in candidates:
        value = extract_first_numeric(candidate)
        if value is not None:
            return value
    return None


def collect_answer_candidates(node: Any, candidates: list[Any]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = key.lower()
            if "answer" in normalized or normalized in {"gold", "target", "label", "expected"}:
                candidates.append(value)
            if isinstance(value, (dict, list, tuple)):
                collect_answer_candidates(value, candidates)
    elif isinstance(node, (list, tuple)):
        for item in node:
            if isinstance(item, (dict, list, tuple)):
                collect_answer_candidates(item, candidates)


def extract_first_numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", value.replace(",", ""))
        return float(match.group(0)) if match else None
    if isinstance(value, (list, tuple)):
        for item in value:
            numeric = extract_first_numeric(item)
            if numeric is not None:
                return numeric
    if isinstance(value, dict):
        for item in value.values():
            numeric = extract_first_numeric(item)
            if numeric is not None:
                return numeric
    return None
