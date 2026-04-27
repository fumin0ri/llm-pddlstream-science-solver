from NL2Plan.main import main as NL2Plan_main
import argparse, os, json
from typing import Literal
import copy

root_dir = os.path.dirname(os.path.realpath(__file__))
domain_dir = os.path.join(root_dir, 'domains')
domains = os.listdir(domain_dir)

def main():
    # Subparser for each planner
    parser = argparse.ArgumentParser(description='Text to Plan.')
    subparsers = parser.add_subparsers(dest='planner', required=True, help="The planner to use. One of 'NL2Plan', 'PDDL0'")
    NL2Plan_parser = subparsers.add_parser("NL2Plan")
    PDDL0_parser = subparsers.add_parser("PDDL0")

    # Joint arguments for each planner
    for sub in [NL2Plan_parser, PDDL0_parser]:
        sub.add_argument('--domain', default='logistics', type=str, help='The domain name (e.g., scibench).', choices=domains, nargs='?')
        sub.add_argument('--task', type=str, default='tasks', help='The relative path to the task JSON file from the domain folder (without .json extension).')
        sub.add_argument('--llm', type=str, default='gpt-4o', help='The LLM engine name.', nargs='?')
        sub.add_argument('--instance_name', type=str, default=None, help='The base name of the subfolder where results are saved.')

    NL2Plan_parser.add_argument('--no_feedback', action='store_true')
    NL2Plan_parser.add_argument('--act_constr_iters', type=int, default=2)
    NL2Plan_parser.add_argument('--act_constr_feedback_level', type=str, choices=["domain", "action", "both"], default="domain", nargs='?')
    NL2Plan_parser.add_argument('--max_step_4_5_6_attempts', type=int, default=5)
    NL2Plan_parser.add_argument('--max_step_4_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--max_step_5_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--max_step_6_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--no_checkpoints', action='store_true')
    NL2Plan_parser.add_argument('--start_from', type=int, default=1, nargs='?')
    NL2Plan_parser.add_argument('--start_dir', type=str, default=None, nargs='?')
    NL2Plan_parser.add_argument('--end_after', type=int, default=6, nargs='?')
    PDDL0_parser.add_argument('--max_attempts', type=int, default=5)
    PDDL0_parser.add_argument('--disable_validation', action='store_true')

    args = parser.parse_args()

    # ドメインの説明文を読み込む
    with open(os.path.join(root_dir, 'domains', args.domain, 'desc.txt'), 'r') as f:
        desc = f.read()
    

    json_relative_path = f'{args.task}.json'
    tasks_json_path = os.path.join(root_dir, 'domains', args.domain, json_relative_path)

    print(f"Attempting to load tasks from: {tasks_json_path}")
    with open(tasks_json_path, 'r') as f:
        tasks = json.load(f)

    # ループ処理
    for i, task_item in enumerate(tasks):
        current_args = copy.deepcopy(args)
        
        problem_text = task_item.get("problem_text")
        unit = task_item.get("unit")
        if not problem_text:
            print(f"Skipping task {i+1} due to missing 'problem_text'.")
            continue

        task_id = i + 1
        current_args.desc_task = f'{desc}\n\n{problem_text} Please answer in the following units: {unit}'

        base_instance_name = args.instance_name if args.instance_name else f"{args.domain}_{args.task.replace('/', '_')}_{args.llm}"
        current_args.instance_name = f"{base_instance_name}_task{task_id}"

        print(f"Running {current_args.planner} on domain {current_args.domain} with task ID {task_id} from {args.task}.json and LLM {current_args.llm}.\n{'-'*50}")

        if current_args.planner == "NL2Plan":
            plan = NL2Plan_planner(current_args)
        elif current_args.planner == "PDDL0":
            plan = PDDL0_planner(current_args)
        else:
            raise ValueError("Invalid planner.")
        
        print(f"\nFinished task ID {task_id}.\n{'='*50}\n")


def NL2Plan_planner(args):
    feedback = None if args.no_feedback else "llm"
    max_4 = args.max_step_4_attempts if args.max_step_4_attempts is not None else args.max_step_4_5_6_attempts
    max_5 = args.max_step_5_attempts if args.max_step_5_attempts is not None else args.max_step_4_5_6_attempts
    max_6 = args.max_step_6_attempts if args.max_step_6_attempts is not None else args.max_step_4_5_6_attempts

    plan = NL2Plan_main(
        domain_name = args.domain,
        domain_task = args.desc_task,
        engine = args.llm,
        act_constr_iters = args.act_constr_iters,
        act_constr_feedback_level = args.act_constr_feedback_level,
        max_step_4_attempts = max_4,
        max_step_5_attempts = max_5,
        max_step_6_attempts = max_6,
        feedback = feedback,
        checkpoints = not args.no_checkpoints,
        start_from = args.start_from,
        start_dir = args.start_dir,
        end_after = args.end_after,
        instance_name = args.instance_name,
    )
    return plan

if __name__ == "__main__":
    main()