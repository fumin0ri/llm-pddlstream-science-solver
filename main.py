import argparse
import copy
import json
import os

from pddlstream_eval import evaluate_task_result

root_dir = os.path.dirname(os.path.realpath(__file__))
domain_dir = os.path.join(root_dir, 'domains')
domains = os.listdir(domain_dir)


def main():
    parser = argparse.ArgumentParser(
        description='Solve SciBench-style tasks with the LLM-to-PDDLStream pipeline.'
    )
    parser.add_argument(
        '--domain',
        default='scibench',
        type=str,
        help='The domain name.',
        choices=domains,
        nargs='?'
    )
    parser.add_argument(
        '--task',
        type=str,
        default='tasks',
        help='The relative path to the task JSON file from the domain folder (without .json extension).'
    )
    parser.add_argument('--llm', type=str, default='gpt-4o', help='The LLM engine name.', nargs='?')
    parser.add_argument(
        '--instance_name',
        type=str,
        default=None,
        help='The base name of the subfolder where results are saved.'
    )
    parser.add_argument('--no_feedback', action='store_true')
    parser.add_argument('--act_constr_iters', type=int, default=2)
    parser.add_argument(
        '--act_constr_feedback_level',
        type=str,
        choices=["domain", "stream", "both"],
        default="stream",
        nargs='?'
    )
    parser.add_argument(
        '--max_step_4_attempts',
        type=int,
        default=5,
        help='Maximum retries per stream during stream construction.'
    )
    parser.add_argument(
        '--skip_pddlstream_eval',
        action='store_true',
        help='Skip executing generated PDDLStream artifacts and SciBench grading.'
    )
    parser.add_argument(
        '--pddlstream_dir',
        type=str,
        default=os.path.join(root_dir, 'external', 'pddlstream'),
        help='Directory where the PDDLStream repository is cloned.'
    )

    args = parser.parse_args()

    with open(os.path.join(root_dir, 'domains', args.domain, 'desc.txt'), 'r') as f:
        desc = f.read()

    tasks_json_path = os.path.join(root_dir, 'domains', args.domain, f'{args.task}.json')
    print(f"Attempting to load tasks from: {tasks_json_path}")
    with open(tasks_json_path, 'r') as f:
        tasks = json.load(f)

    for i, task_item in enumerate(tasks):
        current_args = copy.deepcopy(args)

        problem_text = task_item.get("problem_text")
        unit = task_item.get("unit")
        if not problem_text:
            print(f"Skipping task {i + 1} due to missing 'problem_text'.")
            continue

        task_id = i + 1
        current_args.desc_task = f'{desc}\n\n{problem_text} Please answer in the following units: {unit}'

        base_instance_name = (
            args.instance_name if args.instance_name else f"{args.domain}_{args.task.replace('/', '_')}_{args.llm}"
        )
        current_args.instance_name = f"{base_instance_name}_task{task_id}"

        print(
            f"Running science_solver on domain {current_args.domain} with task ID {task_id} "
            f"from {args.task}.json and LLM {current_args.llm}.\n{'-' * 50}"
        )
        run_science_solver(current_args)

        if not args.skip_pddlstream_eval and current_args.domain == "scibench":
            evaluation = evaluate_task_result(
                project_root=root_dir,
                domain=current_args.domain,
                instance_name=current_args.instance_name,
                task_item=task_item,
                pddlstream_dir=args.pddlstream_dir,
            )
            if evaluation.get("error"):
                print(f"PDDLStream evaluation failed: {evaluation['error']}")
            else:
                predicted = evaluation.get("predicted_answer")
                expected = evaluation.get("expected_answer")
                correct = evaluation.get("correct")
                print(
                    "PDDLStream evaluation: "
                    f"predicted={predicted}, expected={expected}, correct={correct}"
                )
        print(f"\nFinished task ID {task_id}.\n{'=' * 50}\n")


def run_science_solver(args):
    from science_solver.pipeline import run_pipeline

    feedback = None if args.no_feedback else "llm"
    return run_pipeline(
        domain_name=args.domain,
        domain_task=args.desc_task,
        engine=args.llm,
        act_constr_iters=args.act_constr_iters,
        act_constr_feedback_level=args.act_constr_feedback_level,
        max_step_4_attempts=args.max_step_4_attempts,
        feedback=feedback,
        instance_name=args.instance_name,
    )


if __name__ == "__main__":
    main()
