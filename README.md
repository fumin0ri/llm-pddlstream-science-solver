# LLM-PDDLStream Science Solver

This repository implements the thesis pipeline that solves SciBench-style science word problems by translating them into PDDLStream artifacts with an LLM.

## Setup

Clone this repository with submodules:

```bash
git clone --recursive https://github.com/fumin0ri/llm-pddlstream-science-solver.git
cd llm-pddlstream-science-solver
```

If you already cloned it without submodules, run:

```bash
git submodule update --init --recursive
```

Then set up PDDLStream and Fast Downward:

```bash
python scripts/setup_pddlstream.py
```

## Pipeline

The solver runs three stages for each task:

1. Initial facts extraction
2. Stream extraction
3. Stream construction

The generated artifacts are written to the results directory managed by `science_solver`. For SciBench tasks, the root script can also execute the generated PDDLStream files, extract the resulting `answer`, and compare it against the dataset answer.

## Run

```bash
python main.py --domain scibench --task tasks --llm gpt-4o
```

Useful options:

- `--instance_name`: override the output directory prefix
- `--no_feedback`: disable the LLM feedback pass
- `--act_constr_iters`: number of feedback refinement passes during stream construction
- `--act_constr_feedback_level`: choose `domain`, `stream`, or `both`
- `--max_step_4_attempts`: maximum retries per stream during stream construction
- `--skip_pddlstream_eval`: generate artifacts only, without executing PDDLStream
- `--pddlstream_dir`: override the local PDDLStream checkout path

## Notes

- This codebase is a thesis-focused derivative of NL2Plan, but the active implementation is now organized under the `science_solver` package.
- Legacy `PDDL0` and interactive human-feedback paths have been removed from the active workflow.
- `main.py` expects `external/pddlstream` to be available. The provided setup script prepares the submodule and builds Fast Downward.
- PDDLStream execution writes `result.json`, `evaluation.json`, `pddlstream_stdout.log`, and `pddlstream_stderr.log` into each task result directory.
