# LLM-PDDLStream Science Solver

This repository implements the thesis pipeline that solves SciBench-style science word problems by translating them into PDDLStream artifacts with an LLM.

## Pipeline

The solver runs three stages for each task:

1. Initial facts extraction
2. Stream extraction
3. Stream construction

The generated artifacts are written to the results directory managed by `science_solver`.

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

## Notes

- This codebase is a thesis-focused derivative of NL2Plan, but the active implementation is now organized under the `science_solver` package.
- Legacy `PDDL0` and interactive human-feedback paths have been removed from the active workflow.
