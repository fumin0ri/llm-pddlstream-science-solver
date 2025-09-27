from NL2Plan.main import main as NL2Plan_main
from PDDL0.main import main as PDDL0_main
import argparse, os
from typing import Literal

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
        sub.add_argument('--domain', default='logistics', type=str, help='The domain name.', choices=domains, nargs='?')
        sub.add_argument('--task', default=1, type=int, help='The task.', nargs='?')
        sub.add_argument('--llm', type=str, default='gpt-4o', help='The LLM engine name.', nargs='?')
        sub.add_argument('--instance_name', type=str, default=None, help='The name of the subfolder where results are saved.', nargs='?')

    # NL2Plan arguments
    NL2Plan_parser.add_argument('--no_feedback', action='store_true', help='Wheter to disable all LLM feedback. Using human feedback is not supported.')
    NL2Plan_parser.add_argument('--act_constr_iters', type=int, default=2, help='The maximum number of iterations.')
    NL2Plan_parser.add_argument('--act_constr_feedback_level', type=str, choices=["domain", "action", "both"], default="domain", help='The feedback level for Action Construction.', nargs='?')
    NL2Plan_parser.add_argument('--max_step_4_5_6_attempts', type=int, default=5, help='The maximum number of attempts before accepting an attempt even due to failed validation/planning in steps 4, 5, and 6.')
    NL2Plan_parser.add_argument('--max_step_4_attempts', type=int, default=None, help='The maximum number of attempts before accepting an attempt even due to failed validation in step 4. Overwrites max_step_4_5_6_attempts.')
    NL2Plan_parser.add_argument('--max_step_5_attempts', type=int, default=None, help='The maximum number of attempts before accepting an attempt even due to failed validation in step 5. Overwrites max_step_4_5_6_attempts.')
    NL2Plan_parser.add_argument('--max_step_6_attempts', type=int, default=None, help='The maximum number of attempts before accepting an attempt even due to a failed validation or failing to find a plan in step 6. Overwrites max_step_4_5_6_attempts.')
    NL2Plan_parser.add_argument('--no_checkpoints', action='store_true', help='Whether to not save checkpoints.')
    NL2Plan_parser.add_argument('--start_from', type=int, default=1, help='The step to start from.', nargs='?')
    NL2Plan_parser.add_argument('--start_dir', type=str, default=None, help='The path to start from.', nargs='?')
    NL2Plan_parser.add_argument('--end_after', type=int, default=6, help='The step to end after.', nargs='?')

    # PDDL-0 arguments
    PDDL0_parser.add_argument('--max_attempts', type=int, default=5, help='The maximum number of attempts before accepting an attempt even due to failed validation')
    PDDL0_parser.add_argument('--disable_validation', action='store_true', help='Whether to disable all validation. Equivalent to setting max_attempts to 1.')

    args = parser.parse_args()

    with open(os.path.join(root_dir, 'domains', args.domain, f'desc.txt'), 'r') as f:
        desc = f.read()
    with open(os.path.join(root_dir, 'domains', args.domain, f'task{args.task}.txt'), 'r') as f:
        task = f.read()
    args.desc_task = f'{desc}\n\n{task}'

    print(f"Running {args.planner} on domain {args.domain} with task {args.task} and LLM {args.llm}.\n{'-'*50}")

    if args.planner == "NL2Plan":
        plan = NL2Plan_planner(args)
    elif args.planner == "PDDL0":
        plan = PDDL0_planner(args)
    else:
        raise ValueError("Invalid planner.")

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

def PDDL0_planner(args):
    return PDDL0_main(
        domain = args.domain,
        domain_task_desc = args.desc_task,
        llm = args.llm,
        instance_name = args.instance_name,
        max_attempts = args.max_attempts,
        validation_enabled = not args.disable_validation
    )

if __name__ == "__main__":
    main()