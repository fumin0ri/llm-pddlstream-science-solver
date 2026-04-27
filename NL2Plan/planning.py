import os, argparse, re, time
import traceback
from pddl.parser.domain import DomainParser
from pddl.parser.problem import ProblemParser

from .utils.llm_model import LLM_Chat, shorten_messages
from .utils.pddl_generator import PddlGenerator
from .utils.paths import results_dir
from .utils.logger import Logger
from .utils.planner import run_planner, get_plan_files, reset_planner_log
from .utils.pddl_errors import domain_errors, problem_errors
from .utils.paths import planning_prompts as prompt_dir
from .utils.pddl_output_utils import remove_comments

REVISION_HISTORY = []
SEMANTIC_HISTORY = []

@Logger.section("6 Planning")
def planning(optimaly: bool = True, llm_conn: LLM_Chat = None, max_attempts: int = 0, domain_desc: str | None = None) -> list[str] | None:
    global REVISION_HISTORY
    REVISION_HISTORY = []

    if llm_conn is not None:
        llm_conn.reset_token_usage()

    reset_planner_log(PddlGenerator.problem_file) # Reset the log file, in case it exists

    with open(os.path.join(prompt_dir, "system_intro.txt"), "r") as file:
        intro_prompt = file.read()
    intro_prompt = intro_prompt.replace("{domain_desc}", domain_desc)
    REVISION_HISTORY.append({"role": "system", "content": intro_prompt})

    with open(os.path.join(prompt_dir, "domain_intro.txt"), "r") as file:
        intro_prompt = file.read()
    clean_domain = remove_comments(PddlGenerator.get_domain(), skip_pddl_header=True)
    intro_prompt = intro_prompt.replace("{domain}", clean_domain)
    intro_prompt = intro_prompt.replace("{problem}", PddlGenerator.get_problem())
    REVISION_HISTORY.append({"role": "assistant", "content": intro_prompt})

    plan = None
    plan_feedback = None
    plan_given_feedback = None
    plan_feedback_given = False
    remaining_revisions = max_attempts
    while plan is None or not plan_feedback_given:
        PddlGenerator.generate()
        problem_file = PddlGenerator.problem_file
        domain_file = PddlGenerator.domain_file

        if plan is None: # If we've not found a plan yet, try to find one
            cost, plan = run_planner(domain_file=domain_file, problem_file=problem_file, optimaly=optimaly, clean=False)
        elif not plan_feedback_given: # If we have a plan, check if it's correct
            plan_feedback = get_plan_feedback(plan, llm_conn, domain_desc)
            plan_feedback_given = True
            plan_given_feedback = plan # Store the plan for later use
            Logger.print("Plan feedback:\n", plan_feedback)
            remaining_revisions = max_attempts # Reset the revision attempts
            if plan_feedback is not None:
                plan = None # Reset the plan to try again

        # Check if no plan was found
        if plan is None or plan_feedback:
            Logger.print("Problem not solvable. Revising if LLM available.")
            if llm_conn is None or remaining_revisions <= 0:
                Logger.print("No LLM available or out of revision attempts. Exiting.")
                if plan_given_feedback is not None:
                    Logger.print("Returning previously found plan.")
                    plan = plan_given_feedback
                    break
                break
            try:
                remaining_revisions = revise_domain_and_problem(
                    llm_conn, remaining_revisions,
                    succ_plan=plan_given_feedback if plan_feedback is not None else None,
                    succ_feedback=plan_feedback,
                )
                # We only use the feedback once
                plan_feedback = None
            except Exception as e:
                Logger.print("Error revising domain and problem:", e)
                return None

    if llm_conn is not None:
        in_tokens, out_tokens = llm_conn.token_usage()
        Logger.add_to_info(Planning_Tokens=(in_tokens, out_tokens))

    if plan is None:
        Logger.print("No plan found.")
        return None
    Logger.print("Plan with cost ", cost, ":\n - ", "\n - ".join(plan))
    return plan

def revise_domain_and_problem(llm_conn: LLM_Chat, revision_attempts: int, succ_plan : list[str] | None = None, succ_feedback: str | None = None) -> int:
    PddlGenerator.generate()
    problem_file = PddlGenerator.problem_file
    domain_file = PddlGenerator.domain_file
    parse_error = None

    ever_an_error = False
    ever_semantics = False
    while revision_attempts > 0: # Strict since we want revision_attempts = 1 to be the last one
        try:
            Logger.print("Starting revision attempt. ", revision_attempts, " attempts remaining.")
            revision_attempts -= 1

            # If there was a parsing error, try to correct it
            if parse_error is not None:
                Logger.print("Attempting to correct the parsing error.")
                revise_errors(llm_conn, parse_error, None)
                parse_error = None
                continue

            # Identify if there are any errors in the domain and problem files
            domain_error = domain_errors(domain_file)
            problem_error = problem_errors(problem_file, domain_file)

            # If there are errors, revise the domain and problem files
            if domain_error is not None or problem_error is not None:
                ever_an_error = True
                revise_errors(llm_conn, domain_error, problem_error)
                continue

            # If we've fixed anything, try to replan
            if ever_an_error or ever_semantics:
                Logger.print("Errors were corrected. Attempting to replan.")
                revision_attempts += 1 # This attempt doesn't count towards the limit
                break

            # Otherwise, correct the semantics
            Logger.print("Attempting to correct the problem semantics.")
            ever_semantics = True
            revise_semantics(llm_conn, succ_plan=succ_plan, succ_feedback=succ_feedback)
            succ_plan = None # Only use the success plan and feedback once
            succ_feedback = None
        except Exception as e:
            parse_error = str(e)
            Logger.print("Error revising domain and problem: ", e)
            # Print the errors calltrace
            tb = traceback.format_exc()
            Logger.print(tb)

    return revision_attempts

def revise_errors(llm_conn: LLM_Chat, domain_error: str, problem_error: str) -> None:
    global REVISION_HISTORY
    total_errors  =  domain_error if  domain_error is not None else ""
    total_errors += problem_error if problem_error is not None else ""

    with open(os.path.join(prompt_dir, "error_revision.txt"), "r") as file:
        revision_prompt = file.read()
    revision_prompt = revision_prompt.replace("{errors}", total_errors)
    revision_prompt = revision_prompt.replace("{domain}", PddlGenerator.get_domain())
    revision_prompt = revision_prompt.replace("{problem}", PddlGenerator.get_problem())
    REVISION_HISTORY.append({"role": "user", "content": revision_prompt})

    messages = shorten_messages(REVISION_HISTORY)
    llm_output = llm_conn.get_response(messages=messages)
    REVISION_HISTORY.append({"role": "assistant", "content": llm_output})

    # Update domain and problem files
    parse_and_update(llm_output)

def revise_semantics(llm_conn: LLM_Chat, succ_plan: list[str] | None = None, succ_feedback: str | None = None) -> None:
    global REVISION_HISTORY
    global SEMANTIC_HISTORY

    # Identify a possible initial correction
    if succ_feedback is None:
        initial_correction, correction_plan = identify_initial_corrections()
        info = "\n".join([
            "A possible way of solving the problem is to do the following:",
            "{correction}",
            "After which the following plan solves the task:",
            "{correction_plan}",
            "",
            #"However, this was found with a flawed algorithm that can only change the initialization and does not take the meaning of the task and domain into consideration. As such, it is probably better to modify the domain and/or problem in some other manner that actually correctly models the task. Instead, analyze why this correction actually helps and use this analysis to fix the problem.",
            "However, this was found with a flawed algorithm that can only change the initialization and does not take the meaning of the task and domain into consideration. As such, you shouldn't blindly trust this. Instead, you need to change the domain and problem in a way that correctly models the task. Even though these suggestions are all for the problem file, it is probably better to change the domain.",
        ])
        info = info.replace("{correction}", initial_correction).replace("{correction_plan}", correction_plan)
    else:
        info = "\n".join([
            "While we have found a way to solve the task, this solution appears to be flawed. The following plan solves the task:",
            "{succ_plan}",
            "However, we received the following feedback from the user:",
            "{succ_feedback}",
            "",
            "This feedback indicates that the solution is not correct, and we should analyze why the domain and problem files fail and use this analysis to fix the problem.",
        ])
        succ_plan_str = "\t- " + "\n\t- ".join(succ_plan)
        info = info.replace("{succ_plan}", succ_plan_str).replace("{succ_feedback}", succ_feedback)
    history_str = ("\n\n".join(SEMANTIC_HISTORY)) if len(SEMANTIC_HISTORY) > 0 else "No attempts have been made yet"

    with open(os.path.join(prompt_dir, "semantics_revision.txt"), "r") as file:
        revision_prompt = file.read()
    clean_domain = remove_comments(PddlGenerator.get_domain(), skip_pddl_header=True)
    revision_prompt = revision_prompt.replace("{domain}", clean_domain)
    revision_prompt = revision_prompt.replace("{problem}", PddlGenerator.get_problem())
    revision_prompt = revision_prompt.replace("{semantic_history}", history_str)
    revision_prompt = revision_prompt.replace("{info}", info)
    REVISION_HISTORY.append({"role": "user", "content": revision_prompt})

    #messages = shorten_messages(REVISION_HISTORY)
    messages = [REVISION_HISTORY[0], REVISION_HISTORY[-1]] # For this, the last message actually contains the most recent domain and problem
    llm_output = llm_conn.get_response(messages=messages)
    REVISION_HISTORY.append({"role": "assistant", "content": llm_output})

    if "\n# Changes" in llm_output:
        summary_section = llm_output.split("\n# Changes")[1].split("# Domain")[0].split("# Problem")[0]
        indent_level = 1
        last_line_indent = False
        summary = f"\tAttempt {len(SEMANTIC_HISTORY)+1}:\n"
        for line in summary_section.split("\n"):
            clean = line.strip(" -*\t")
            if clean == "":
                if not last_line_indent:
                    indent_level -= 1
                continue
            last_line_indent = False
            clean = "\t"*indent_level + "- " + clean
            if clean.endswith(":"):
                indent_level += 1
                last_line_indent = True
            summary += clean + "\n"
        SEMANTIC_HISTORY.append(summary)

    # Update domain and problem files
    parse_and_update(llm_output)

def identify_initial_corrections(domain_file=None, problem_file=None) -> tuple[str, str]:

    #return "No suggestions available."

    if domain_file is None:
        domain_file = PddlGenerator.domain_file
        problem_file = PddlGenerator.problem_file

    domain = open(domain_file, "r").read()
    problem = open(problem_file, "r").read()

    init_domain, init_problem = generate_initializable_domain(domain, problem)
    init_domain_file = domain_file.replace(".pddl", "-init.pddl")
    init_problem_file = problem_file.replace(".pddl", "-init.pddl")

    with open(init_domain_file, "w") as file:
        file.write(init_domain)
    with open(init_problem_file, "w") as file:
        file.write(init_problem)

    # Run the planner to find initializations
    Logger.print("Running planner to identify initializations.", subsection=False)
    cost, plan = run_planner(init_domain_file, init_problem_file, clean=True, optimaly=True, unit_cost=False)
    Logger.print("Initializable plan: ", plan, " with cost ", cost)

    # Remove the temporary files
    #os.remove(init_domain_file)
    #os.remove(init_problem_file)

    if plan is None:
        # If planner failed, return no suggestions
        return "No suggestions available.", "No suggestions available."

    if plan[0] == "start":
        # If the plan starts with "start", we don't need to make any corrections
        return "No changes necessary, problem is already solvable.", plan[1:]

    # Format the corrections
    correction_steps = plan[:plan.index("start")] if "start" in plan else plan # If we never started, the entire plan is the correction (we set the goal to true)
    cor_plan = plan[plan.index("start")+1:] if ("start" in plan and not plan[-1] == "start") else "The initialization solves the problem. There is no need to perform any actions." # Remove the correction steps from the plan
    corrections = []
    for step in correction_steps:
        if "_true" in step:
            pred = step.split("_true")[0]
            args = " ".join(step.split(" ")[1:])
            corrections.append(f"Adding '({pred} {args})' to the initial state.")
        elif "_false" in step:
            pred = step.split("_false")[0]
            args = " ".join(step.split(" ")[1:])
            corrections.append(f"Removing '({pred} {args})' from the initial state.")
        else:
            # This should not happen
            Logger.print("WARNING: Unexpected step in the plan: ", step)

    if len(corrections) == 0:
        # This should not happen
        cor_str = "No changes necessary, problem is already solvable."
    else:
        cor_str = "\t- " + "\n\t- ".join(corrections) if not type(corrections) == str else corrections
    if not type(cor_plan) == str:
        plan_str = "\t- " + "\n\t- ".join(cor_plan)
    else:
        plan_str = cor_plan
    return cor_str, plan_str

def generate_initializable_domain(domain, problem) -> tuple[str,str]:
    domain = domain.lower()
    problem = problem.lower()

    def add_to_init(problem, grounded_predicate) -> str:
        return problem.replace("(:init", f"(:init\n\t\t{grounded_predicate}")

    def add_to_predicates(domain, lifted_predicate) -> str:
        return domain.replace("(:predicates", f"(:predicates\n\t\t{lifted_predicate}")

    def goal_predicate_name(predicate_name: str) -> str:
        return f"goal_{predicate_name}"

    def initially_predicate_name(predicate_name: str) -> str:
        return f"initially_{predicate_name}"

    def indent(text: str, level: int = 1) -> str:
        return text.replace("\n", "\n" + "\t"*level)

    def started_action(action) -> str:
        # Replace the action to require the "started" predicate to be true and have a cost of 1
        lines = str(action).split("\n")
        lines[2] = lines[2].replace(":precondition", ":precondition (and (started)") + ")" # Add the "started" predicate
        lines[3] = lines[3].replace(":effect", ":effect (and (increase (total-cost) 1)") + ")" # Add the cost of 1
        return "\t" + "\n\t".join(lines)

    commented_domain = domain # Save the original domain for later use
    def predicate_action(predicate, basic: bool = False) -> tuple[str,str]:
        domain = commented_domain
        # Return two actions, one setting the predicate to true and the other to false
        parameters = " ".join([f"?{term._name} - {next(iter(term._type_tags))}" for term in predicate._terms])
        arguments = " ".join([f"?{term._name}" for term in predicate._terms])
        pred_name = predicate.name
        pred_call = f"({pred_name} {arguments})"
        initially_pred_name = initially_predicate_name(pred_name)
        goal_pred_name = goal_predicate_name(pred_name)

        def setter_action(name:str, precondition: str, set: bool, cost: str) -> str:
            effect = f"(and {pred_call} (increase (total-cost) {cost}))" if set else f"(and (not {pred_call}) (increase (total-cost) {cost}))"
            return f"\t(:action {name}\n\t\t:parameters ({parameters})\n\t\t{precondition}\n\t\t:effect {effect}\n\t)"

        goal_precond = f":precondition (and (not (started)) ({goal_pred_name} {arguments}))"
        base_precond = f":precondition (and (not (started)) (not ({goal_pred_name} {arguments})))"

        if basic:# or len(predicate._terms) == 0:
            # The basic version is the closest to the original. It models two levels: goal and not goal

            true_goal  = setter_action(f"{pred_name}_true_goal",  goal_precond, True,  1000000)
            true_base  = setter_action(f"{pred_name}_true_base",  base_precond, True,  100)
            false_goal = setter_action(f"{pred_name}_false_goal", goal_precond, False, 1000000)
            false_base = setter_action(f"{pred_name}_false_base", base_precond, False, 100)

            return [true_base, true_goal, false_base, false_goal]

        # The LLM version trusts that the LLM has marked the predicates correctly with `NOINIT`, `SINGULAR` or `MAXONCE(?PARAM)`

        true_goal  = setter_action(f"{pred_name}_true_goal",  goal_precond, True,  1000000)
        true_base  = setter_action(f"{pred_name}_true_base",  base_precond, True,  10000)
        false_goal = setter_action(f"{pred_name}_false_goal", goal_precond, False, 1000000)
        false_base = setter_action(f"{pred_name}_false_base", base_precond, False, 10000)

        def keyword_matches(predicate, keyword):
            reg = rf"{keyword.lower()}\([^()]*\)"
            predicate_str = domain.split("(:predicates")[1].split("(:action")[0]
            pred_name = predicate.name
            for line in predicate_str.split("\n"):
                line = line.strip()
                if pred_name in line:
                    return re.findall(reg, line)
            return []

        def singular_precond(predicate):
            # The predicate is only allowed to be true at once, so the precondition is that it is not true anywhere else
            params = " ".join([f"?{term._name}_other - {next(iter(term._type_tags))}" for term in predicate._terms])
            args = " ".join([f"?{term._name}_other" for term in predicate._terms])
            return f":precondition (and (not (started)) (not ({goal_pred_name} {arguments})) \n\t\t\t(not (exists ({params}) ({pred_name} {args})))\n\t\t)"

        def object_not_used(predicate, object):
            # The predicate is only allowed to be true for the given objects once
            params = " ".join([f"?{term._name}_other - {next(iter(term._type_tags))}" for term in predicate._terms if f"?{term._name}" != object])
            args = " ".join([f"?{term._name}_other" if f"?{term._name}" != object else f"?{term._name}" for term in predicate._terms])
            return f"(not (exists ({params}) ({pred_name} {args})))"

        def maxonce_precond(predicate, objects):
            # The predicate is only allowed to be true for each given objects once
            object_preconds = [object_not_used(predicate, obj) for obj in objects]
            object_preconds_str = "\n\t\t\t" + "\n\t\t\t".join(object_preconds)
            return f":precondition (and (not (started)) (not ({goal_pred_name} {arguments})) {object_preconds_str}\n\t\t)"

        actions = [true_goal, true_base, false_goal, false_base]

        #print(f"Predicate: {pred_name}", keyword_matches(predicate, "NOINIT"), keyword_matches(predicate, "SINGULAR"), keyword_matches(predicate, "MAXONCE"))
        if not keyword_matches(predicate, "NOINIT"):
            # If "NOINIT" don't add any semantics for this predicate
            if keyword_matches(predicate, "SINGULAR"):
                # If "SINGULAR" add semantics for the predicate
                actions.insert(0, setter_action(f"{pred_name}_true_sem",  singular_precond(predicate), True,  100))
                # Setting a singular to false is always semantic
                actions.insert(0, setter_action(f"{pred_name}_false_sem", base_precond, False, 100))
            elif keyword_matches(predicate, "MAXONCE") and len(predicate._terms) > 1:
                # If "MAXONCE" add semantics for the predicate
                objects = [kw.split("(")[1].split(")")[0] for kw in keyword_matches(predicate, "MAXONCE")]
                objects = [obj.split(",") for obj in objects]
                flat_objects = []
                for obj in objects:
                    flat_objects += obj if type(obj) == list else [obj]
                flat_objects = [obj.strip() for obj in flat_objects if obj.strip() != ""]
                actions.insert(0, setter_action(f"{pred_name}_true_sem",  maxonce_precond(predicate, flat_objects), True,  100))
                actions.insert(0, setter_action(f"{pred_name}_false_sem", base_precond, False, 100))

        return actions

    parsed = DomainParser()(domain)
    actions = parsed.actions
    predicates = parsed.predicates

    # --- Modify the domain ---
    # Retain the header of the domain
    domain = domain.split("(:action")[0]

    # Add the "action-cost" and ":disjunctive-preconditions" requirement to the domain
    if not ":actin-costs" in domain:
        domain = domain.replace("(:requirements", "(:requirements :action-costs")
    if not ":disjunctive-preconditions" in domain:
        domain = domain.replace("(:requirements", "(:requirements :disjunctive-preconditions")

    # For each predicate, add the "invert" predicate
    for predicate in predicates:
        parameters = [f"?{term._name} - {next(iter(term._type_tags))}" for term in predicate._terms]
        parameters = " ".join(parameters)
        in_goal = f"({goal_predicate_name(predicate.name)} {parameters})"
        in_init = f"({initially_predicate_name(predicate.name)} {parameters})"
        domain = add_to_predicates(domain, in_goal)
        #domain = add_to_predicates(domain, in_init) # We don't need these atm

    # Add the "started" predicates to the domain
    domain = add_to_predicates(domain, "(started)")

    # Add the "total-cost" function to the domain
    domain += "(:functions (total-cost))\n\n\n"

    # Add the "start" action to the domain
    start_action = f"\t(:action start\n\t\t:parameters () \n\t\t:precondition (and (not (started)))\n\t\t:effect (started)\n\t)"
    domain += start_action + "\n"*3

    # Add the modified actions to the domain
    for action in actions:
        domain += started_action(action) + "\n"*3

    # Add the predicate actions to the domain
    for predicate in predicates:
        for act in predicate_action(predicate):
            domain += act + "\n"*3

    # Finish the domain with closing brackets
    domain += ")"

    # --- Modify the problem ---f
    # Check which predicates are in the goal

    # Extract the init section, removing closing for init
    init_str = problem.split("(:init")[1].split("(:goal")[0].rsplit(")",1)[0]
    init_clean = re.sub(r';.*\n', '', init_str) # Remove comments
    init_atoms = re.findall(r'\([\w\-]+\s+[^()]*?\)', init_clean)
    for atom in init_atoms:
        atom_safe = atom.replace("(", "\(").replace(")", "\)")
        neg_regex = rf'\(\s*not\s*{atom_safe}\s*\)'
        if len(re.findall(neg_regex, init_clean)) > 0:
            # Check if the atom is actually negated
            continue
        # Mark the atom as initially true
        inner_atom = atom.split("(",1)[1].rsplit(")",1)[0]
        to_add = f"({initially_predicate_name(inner_atom)})"
        #problem = add_to_init(problem, to_add) # We don't need these atm

    # Extract the goal section, removing closing for problem and goal
    goal_str = problem.split("(:goal")[1].rsplit(")",2)[0]
    goal_clean = re.sub(r';.*\n', '', goal_str) # Remove comments
    goal_atoms = re.findall(r'\([\w\-]+\s+[^()]*?\)', goal_clean)
    for atom in goal_atoms:
        to_add = f"(goal_{atom[1:]}"
        problem = add_to_init(problem, to_add)
    # Add the minimization goal
    problem = problem.strip()[:-1] + "\t(:metric minimize (total-cost))\n)"
    # Initialize the value of total-cost
    problem = add_to_init(problem, "(= (total-cost) 0)")

    return domain, problem

def parse_and_update(llm_output: str, overwrite: bool = True) -> tuple[str,str]:
    llm_output = clean_llm_output(llm_output)
    llm_output = "\n" + llm_output # Add a newline at the start to make sure the first header is found
    # Split the output into domain and problem
    domain_section = None
    for header in ["\n# Domain", "\n## Domain", "\n### Domain"]:
        if header in llm_output:
            domain_section = llm_output.split(header,1)[1]
            break
    if domain_section is not None:
        domain_section = domain_section.split("\n# Problem")[0].split("\n# Changes")[0]

    problem_section = None
    for header in ["\n# Problem", "\n## Problem", "\n### Problem"]:
        if header in llm_output:
            problem_section = llm_output.split(header,1)[1]
            break
    if problem_section is not None:
        problem_section = problem_section.split("\n# Domain")[0].split("\n# Changes")[0]

    #if domain_section is None and problem_section is None:
    #    raise Exception("No domain or problem found in LLM output. They must each be specified in independent markdown blocks under their respective headers.")

    #if  domain_section is not None and  domain_section.count("```") > 2 or \
    #   problem_section is not None and problem_section.count("```") > 2:
    #    raise Exception("No PDDL found in either the domain or problem sections. They must each be specified in independent markdown blocks under their respective headers.")

    Logger.log("The domain section is:", "-"*30, domain_section, "-"*30, sep="\n", subsection=False)
    Logger.log("The problem section is:", "-"*30, problem_section, "-"*30, sep="\n", subsection=False)

    # Extract the code from the domain and problem sections. If there are multiple blocks we take the last one. Adapted in case the last block is not closed.
    if domain_section is None:
        domain = None
    else:
        #if domain_section.count("```") == 0:
        #    domain_indx = 0
        if domain_section.count("```") <= 1:
            domain_indx = 1
        else:
            domain_indx = -2 if domain_section.count("```") % 2 == 0 else -1 # Adapted in case the last block is not closed.
        if domain_section.count("```") == 0:
            domain = None
        else:
            domain = domain_section.split("```")[domain_indx]

    if problem_section is None:
        problem = None
    else:
        #if problem_section.count("```") == 0:
        #    problem_indx = 0
        if problem_section.count("```") <= 1:
            problem_indx = 1
        else:
            problem_indx = -2 if problem_section.count("```") % 2 == 0 else -1 # Adapted in case the last block is not closed.
        if problem_section.count("```") == 0:
            problem = None
        else:
            problem = problem_section.split("```")[problem_indx]

    # Overwrite the domain and problem files
    errors = []
    if domain is not None:
        if not ("(define" in domain and "(:types" in domain and "(:predicates" in domain and "(:requirements" in domain):
            domain = None
            Logger.print("WARNING: The domain appears to be malformed.")
            errors.append("The domain appears to be malformed. It must contain the '(define', '(:requirements', (:types', and '(:predicates' sections.")
        else:
            domain = f"(define {domain.split('(define',maxsplit=1)[1]}" # Remove any leading text
            if overwrite:
                PddlGenerator.overwrite_domain(domain)
            Logger.print("Domain updated to:", "-"*30, domain, "-"*30, sep="\n")
    else:
        Logger.print("WARNING: No domain found in the output. Retaining the current domain.")

    if problem is not None:
        if not ("(define" in problem and "(:objects" in problem and "(:init" in problem and "(:goal" in problem):
            problem = None
            Logger.print("WARNING: The problem appears to be malformed.")
            errors.append("The problem appears to be malformed. It must contain the '(define', '(:objects', '(:init', and '(:goal' sections.")
        else:
            problem = f"(define {problem.split('(define',maxsplit=1)[1]}" # Remove any leading text
            if overwrite:
                PddlGenerator.overwrite_problem(problem)
            Logger.print("Problem updated to:", "-"*30, problem, "-"*30, sep="\n")
    else:
        Logger.print("WARNING: No problem found in the output. Retaining the current problem.")

    if overwrite:
        PddlGenerator.generate()

    if len(errors) > 0:
        Logger.print("The domain and problem files were not updated due to the following errors:\n-", "\n-".join(errors))
        raise Exception("The domain and problem files were not updated due to the following errors:\n-", "\n-".join(errors))

    return domain, problem

def get_plan_feedback(plan, llm_conn : LLM_Chat, domain_desc: str | None):
    with open(os.path.join(prompt_dir, "plan_feedback.txt"), "r") as file:
        feedback_template = file.read().strip()
    if len(plan) > 0:
        plan_str = "\t- " + "\n\t- ".join(plan)
    else:
        plan_str = "No actions necessary, the problem starts solved."
    feedback_msg = feedback_template.replace("{plan}", plan_str)
    feedback_msg = feedback_msg.replace("{domain_desc}", str(domain_desc))

    feedback = llm_conn.get_response(feedback_msg)

    if "no feedback" in feedback.lower() or len(feedback.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback)
        return None

    if feedback.count("```") == 2:
        feedback = feedback.split("```")[1].strip()

    Logger.print("FEEDBACK:\n", feedback)

    return feedback

def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```")
    return llm_output