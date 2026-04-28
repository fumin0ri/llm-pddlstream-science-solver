import sys, os, contextlib, argparse, subprocess

from .paths import scorpion_dir, downward_dir
from .logger import Logger

def run_planner(domain_file, problem_file, plan_file = None, log_file = None, optimaly: bool = True, clean: bool = False, use_downward: bool = True, time_limit: int = 2, unit_cost: bool = True) -> list[str] | None:
    scorpion_file = os.path.join(scorpion_dir, "fast-downward.py")
    downward_file = os.path.join(downward_dir, "fast-downward.py")

    if plan_file is None:
        plan_file = os.path.join(os.path.dirname(problem_file), "plan.txt")
    if log_file is None:
        log_file = os.path.join(os.path.dirname(problem_file), "planner_log.txt")
    sas_file = os.path.join(os.path.dirname(problem_file), "output.sas")

    Logger.print(f"Problem file: {problem_file}", subsection=False)
    Logger.print(f"Domain file: {domain_file}", subsection=False)
    Logger.print(f"Plan file: {plan_file}", subsection=False)
    Logger.print(f"Log file: {log_file}", subsection=False)

    planner = downward_file if use_downward else scorpion_file

    if unit_cost:
        heuristics = [
            "let(hlm, landmark_sum(lm_reasonable_orders_hps(lm_rhw()),pref=false),"
            "let(hff, ff(),"
            """iterated([
                lazy_greedy([hff,hlm],preferred=[hff,hlm]),
                lazy_wastar([hff,hlm],preferred=[hff,hlm],w=5),
                lazy_wastar([hff,hlm],preferred=[hff,hlm],w=3),
                lazy_wastar([hff,hlm],preferred=[hff,hlm],w=2),
                lazy_wastar([hff,hlm],preferred=[hff,hlm],w=1)
            ],repeat_last=true,continue_on_fail=true)))""",
        ]
    else:
        heuristics = [
            # Added axioms=approximate_negative to all heuristics
            "let(hlm1, landmark_sum(lm_reasonable_orders_hps(lm_rhw()),transform=adapt_costs(one),pref=false,axioms=approximate_negative),"
            "let(hff1, ff(transform=adapt_costs(one),axioms=approximate_negative),"
            "let(hlm2, landmark_sum(lm_reasonable_orders_hps(lm_rhw()),transform=adapt_costs(plusone),pref=false,axioms=approximate_negative),"
            "let(hff2, ff(transform=adapt_costs(plusone),axioms=approximate_negative),"
            """iterated([
                lazy_greedy([hff1,hlm1],preferred=[hff1,hlm1],
                    cost_type=one,reopen_closed=false),
                lazy_greedy([hff2,hlm2],preferred=[hff2,hlm2],
                    reopen_closed=false),
                lazy_wastar([hff2,hlm2],preferred=[hff2,hlm2],w=5),
                lazy_wastar([hff2,hlm2],preferred=[hff2,hlm2],w=3),
                lazy_wastar([hff2,hlm2],preferred=[hff2,hlm2],w=2),
                lazy_wastar([hff2,hlm2],preferred=[hff2,hlm2],w=1)
            ],repeat_last=true,continue_on_fail=true)))))"""
        ]

    if optimaly:
        args = [
            planner,
            "--overall-time-limit", f"{time_limit}m",
            "--keep-sas-file",
            "--sas-file",
            sas_file, # SAS file
            "--plan-file",
            plan_file, # Plan file
            "--run-all",
            domain_file, # Domain file
            problem_file, # Problem file
            "--search",
            *heuristics,
        ]
    else:
        args = [
            planner,
            "--overall-time-limit", f"{time_limit}m",
            "--keep-sas-file",
            "--sas-file",
            sas_file, # SAS file
            "--plan-file",
            plan_file, # Plan file
            "--search",
            "let(hlm, landmark_sum(lm_factory=lm_reasonable_orders_hps(lm_rhw()),transform=adapt_costs(one),pref=false),"
            "let(hff, ff(transform=adapt_costs(one)),"
            """lazy_greedy([hff,hlm],preferred=[hff,hlm],
                                    cost_type=one,reopen_closed=false)))""",
            domain_file, # Domain file
            problem_file, # Problem file
        ]

    # Check if plan file(s) already exist, if so remove them
    for file in get_plan_files(plan_file):
        os.remove(file)

    # Run planner
    try:
        with open(log_file, "a") as f:
            f.write("-"*80 + "\n")
            f.write(" ".join(args) + "\n")
            f.write("-"*80 + "\n")
            f.flush()  # Make sure this part is written first
            subprocess.run(args, stdout=f, stderr=f)
            f.write("-"*80 + "\n"*3)
            f.flush()  # Make sure this part is written first

    except Exception as e:
        Logger.print("Error running planner: \n\t", e)

    # Find plan, output as a file
    cost, plan = get_plan(plan_file)

    if clean:
        for file in get_plan_files(plan_file):
            os.remove(file)

    return cost, plan

def get_plan(plan_file) -> tuple[int | None, list[str] | None]:
    """Get cost and plan from file specified by args, or None, None if no plan found."""
    # Get all plan files
    plan_files = get_plan_files(plan_file)

    # If no plan files found, return infinity and None
    if len(plan_files) == 0:
        return float("inf"), None

    # Read all plan files and return the best plan
    lowest_cost, best_plan = float("inf"), None
    for file in plan_files:
        cost, plan = read_plan_file(file)
        if cost < lowest_cost:
            lowest_cost, best_plan = cost, plan
    return lowest_cost, best_plan

def read_plan_file(file: str) -> tuple[float, list[str] | None]:
    """Read plan from file."""
    cost = float("inf")
    try:
        with open(file, "r") as file:
            lines = file.readlines()
            plan = []
            for line in lines:
                if line[0] == ";":
                    cost = int(line.split(" ")[3])
                else:
                    plan.append(line.strip(" \n()"))
    except FileNotFoundError:
        cost, plan = float("inf"), None
    return cost, plan

def get_plan_files(plan_file) -> list[str]:
    """Get all plan files in the directory specified by args."""
    plan_dir = os.path.dirname(plan_file)
    plan_base = os.path.basename(plan_file)
    plan_files = [os.path.join(plan_dir,f) for f in os.listdir(plan_dir) if f.startswith(plan_base)]
    return plan_files

def reset_planner_log(problem_file):
    """Reset the scorpion log file."""
    log_file = os.path.join(os.path.dirname(problem_file), "planner_log.txt")
    with open(log_file, "w") as f:
        f.write("")