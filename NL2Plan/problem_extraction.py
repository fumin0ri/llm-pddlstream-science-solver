import os

from .utils.paths import state_goal_extraction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.pddl_types import Predicate, ParameterList
from .utils.pddl_output_utils import combine_blocks
from .utils.human_feedback import human_feedback
from .utils.pddl_errors import problem_errors
from .hierarchy_construction import Hierarchy
from .utils.llm_model import LLM_Chat, get_llm, shorten_messages

REVISION_HISTORY = None

@Logger.section("5 Problem Extraction")
def problem_extraction(
        llm_conn: LLM_Chat,
        domain_desc_str: str,
        type_hierarchy: Hierarchy,
        predicates: list[Predicate],
        messages: list[dict[str, str]] | None = None,
        error: Exception | None = None,
        remaining_attempts: int = None,
        shorten_message: bool = False,
        feedback: str | None = None,
        max_attempts: int = 5,
        revise_problem_iters: int = 0,
    ) -> tuple[str, str, str]:
    """Extract the goal, state, and objects from the LLM output given the domain description, type hierarchy, and predicates."""

    if remaining_attempts is None:
        # This is the first call, so we set the remaining attempts to the maximum
        remaining_attempts = max_attempts
        llm_conn.reset_token_usage()
        if max_attempts < 1:
            raise ValueError("The maximum number of attempts during Problem Extraction (step 5) must be at least 1.")

    if messages is None:
        predicate_str = "\n".join([f"- {pred['signature']}: {pred['desc']}" for pred in predicates])

        with open(os.path.join(prompt_dir, "main.txt")) as f:
            goal_state_extr_template = f.read().strip()
        goal_state_extr_prompt = goal_state_extr_template.replace('{domain_desc}', domain_desc_str)
        goal_state_extr_prompt = goal_state_extr_prompt.replace('{type_hierarchy}', str(type_hierarchy))
        goal_state_extr_prompt = goal_state_extr_prompt.replace('{predicates}', predicate_str)
        goal_state_extr_prompt = goal_state_extr_prompt.replace('{actions}', PddlGenerator.action_descs())

        Logger.log("PROMPT:\n", goal_state_extr_prompt)
        messages = [{'role': 'user', 'content': goal_state_extr_prompt}]
    elif error is not None:
        with open(os.path.join(prompt_dir, "error.txt")) as f:
            goal_corr_template = f.read().strip()
        goal_corr_prompt = goal_corr_template.replace('{error_msg}', str(error))
        goal_corr_prompt = goal_corr_prompt.replace('{task}', "goal and state extraction")
        messages.append({'role': 'user', 'content': goal_corr_prompt})
        Logger.log("Error Correction Prompt:\n", goal_corr_prompt)
    else:
        raise ValueError("If messages are provided, error must also be provided.")

    messages_to_send = messages if not shorten_message else shorten_messages(messages)
    llm_output = llm_conn.get_response(messages=messages_to_send)
    messages.append({'role': 'assistant', 'content': llm_output})

    objects_str, state_str, goal_str = None, None, None

    if  not "## Object Instances" in llm_output or \
        not "## State" in llm_output or \
        not "## Goal" in llm_output:
        Logger.print("Error before extraction: Could not find all necessary sections in the LLM output.")
        if remaining_attempts <= 1: # Should only need == 1, but just in case
            pass
        else:
            error = "Could not find all necessary sections in the LLM output. The output should contain the section '## Object Instances', '## State', and '## Goal'."
            return problem_extraction(
                llm_conn=llm_conn, domain_desc_str=domain_desc_str, type_hierarchy= type_hierarchy,
                predicates=predicates, messages=messages, error=error,
                remaining_attempts=remaining_attempts - 1, shorten_message=shorten_message,
                feedback=feedback, revise_problem_iters=revise_problem_iters, max_attempts=max_attempts
            )

    try:
        objects, objects_str = parse_objects(llm_output, type_hierarchy, predicates, check_errors=False)
        PddlGenerator.set_objects(objects_str)
        PddlGenerator.set_goal("(and)") # Set an empty goal to avoid errors
        PddlGenerator.generate()
        errors = problem_errors(PddlGenerator.problem_file, PddlGenerator.domain_file)
        if errors is not None:
            raise ValueError(errors)
    except ValueError as error:
        Logger.print(f"Error during object construction ({remaining_attempts} attempts left):\n{error}")
        if remaining_attempts <= 1: # Should only need == 1, but just in case
            objects, objects_str = parse_objects(llm_output, type_hierarchy, predicates, check_errors=False)
        else:
            return problem_extraction(
                llm_conn=llm_conn, domain_desc_str=domain_desc_str, type_hierarchy= type_hierarchy,
                predicates=predicates, messages=messages, error=error,
                remaining_attempts=remaining_attempts - 1, shorten_message=shorten_message,
                feedback=feedback, revise_problem_iters=revise_problem_iters, max_attempts=max_attempts
            )
    Logger.print("Extracted objects: \n", objects_str)
    PddlGenerator.set_objects(objects_str)

    try:
        state_str = parse_state(llm_output, type_hierarchy, predicates, objects, check_errors=False)
        PddlGenerator.set_init(state_str)
        PddlGenerator.set_goal("(and)") # Set an empty goal to avoid errors
        PddlGenerator.generate()
        errors = problem_errors(PddlGenerator.problem_file, PddlGenerator.domain_file)
        if errors is not None:
            raise ValueError(errors)
    except ValueError as error:
        Logger.print(f"Error during state construction ({remaining_attempts} attempts left):\n{error}")
        if remaining_attempts <= 1: # Should only need == 1, but just in case
            state_str = parse_state(llm_output, type_hierarchy, predicates, objects, check_errors=False)
        else:
            return problem_extraction(
                llm_conn=llm_conn, domain_desc_str=domain_desc_str, type_hierarchy= type_hierarchy,
                predicates=predicates, messages=messages, error=error,
                remaining_attempts=remaining_attempts - 1, shorten_message=shorten_message,
                feedback=feedback, revise_problem_iters=revise_problem_iters, max_attempts=max_attempts
            )
    Logger.print("Extracted state: \n", state_str)
    PddlGenerator.set_init(state_str)

    try:
        goal_str = parse_goal(llm_output, type_hierarchy, predicates, objects, check_errors=False)
        PddlGenerator.set_goal(goal_str)
        PddlGenerator.generate()
        errors = problem_errors(PddlGenerator.problem_file, PddlGenerator.domain_file)
        if errors is not None:
            raise ValueError(errors)
    except ValueError as error:
        Logger.print(f"Error during goal construction ({remaining_attempts} attempts left):\n{error}")
        if remaining_attempts <= 1: # Should only need == 1, but just in case
            goal_str = parse_goal(llm_output, type_hierarchy, predicates, objects, check_errors=False)
        else:
            return problem_extraction(
                llm_conn=llm_conn, domain_desc_str=domain_desc_str, type_hierarchy= type_hierarchy,
                predicates=predicates, messages=messages, error=error,
                remaining_attempts=remaining_attempts - 1, shorten_message=shorten_message,
                feedback=feedback, revise_problem_iters=revise_problem_iters, max_attempts=max_attempts
            )
    Logger.print(f"Extracted goal: \n", goal_str)
    PddlGenerator.set_goal(goal_str)

    # After we succeed, or if we run out of attempts, we ask for feedback
    if feedback is not None:

        # This will initialize with empty strings if the extraction failed
        if objects_str is None:
            objects_str = PddlGenerator.get_objects()
        if state_str is None:
            state_str = PddlGenerator.get_init()
        if goal_str is None:
            goal_str = PddlGenerator.get_goal()

        if feedback.lower() == "human":
            msg  =  "The goal and state have been extracted. Please review them and provide feedback.\n\n"
            msg += f"Objects:\n{objects_str}\n\nState:\n{state_str}\n\nGoal:\n{goal_str}\n\n"
            feedback_msg = human_feedback(msg)
        else:
            feedback_msg = get_llm_feedback(llm_conn, type_hierarchy, predicates, domain_desc_str, objects_str, state_str, goal_str)
        Logger.print("Received feedback:\n", feedback_msg)
        PddlGenerator.generate()
        error_msg = problem_errors(PddlGenerator.problem_file, PddlGenerator.domain_file)
        if error_msg is not None:
            Logger.print("Error in the generated problem:\n", error_msg)
            if feedback_msg is None:
                feedback_msg = error_msg
            else:
                feedback_msg += "\n"*3 + "In addition to the above, the following syntactical issues exists within the domain:\n\n" + error_msg + "\n\n These issues also need to be addressed." + "\n"*3
        if feedback_msg is not None:
            Logger.print("Sending feedback:\n", feedback_msg)
            return problem_extraction(
                llm_conn=llm_conn, domain_desc_str=domain_desc_str, type_hierarchy= type_hierarchy,
                predicates=predicates, messages=messages, error=feedback_msg,
                remaining_attempts=max_attempts, shorten_message=shorten_message,
                feedback=None, revise_problem_iters=revise_problem_iters, max_attempts=max_attempts
            ) # Note that we reset the remaining attempts here, but disable feedback

    domain = PddlGenerator.get_domain()
    problem = PddlGenerator.get_problem()
    with open(os.path.join(prompt_dir, "revision.txt")) as f:
        revision_template = f.read().strip()
    revision_template = revision_template.replace('{domain_desc}', domain_desc_str)
    revision_template = revision_template.replace('{domain}', domain)
    revision_template = revision_template.replace('{problem}', problem)

    problem_revision_error = None
    PddlGenerator.generate()
    while revise_problem_iters > 0:
        revise_problem_iters -= 1

        revisions = problem_revision(llm_conn, revision_template, problem_revision_error)
        PddlGenerator.overwrite_problem(revisions)

        errors = problem_errors(PddlGenerator.problem_file, PddlGenerator.domain_file)
        if errors is not None:
            Logger.print(f"Failed to parse revised problem:\n{errors}. Retrying iteration {revise_problem_iters}.", subsection=False)
            problem_revision_error = errors
            continue

        if revisions is None:
            Logger.print("No new problem received. Exiting revision loop.")
            PddlGenerator.overwritten_problem = None
            break

        goal_str = None
        state_str = None
        objects_str = None
        objects = None
        break

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Problem_Extraction_Tokens=(in_tokens, out_tokens))

    return goal_str, state_str, objects_str

def parse_objects(llm_output: str, type_hierarchy: Hierarchy, predicates: list[Predicate], check_errors: bool = True) -> tuple[dict[str, str], str]:
    """Extract the objects from the LLM output and return them as a string."""
    try:
        objects_head = extract_heading(llm_output, "\n## Object Instances")
    except:
        # It's possible that this is the first section, so no newline before the heading
        objects_head = extract_heading(llm_output, "## Object Instances")
    objects_raw = combine_blocks(objects_head)
    objects_clean = unify_comments(objects_raw, comments=[':','//','#',';','(']) # Unify comments
    objects = [(
            obj.split(" - ")[0].strip(" `"),
            obj.split(" - ")[1].strip(" `").split(";")[0].strip(" `").split(" ")[0].lower(),
            (obj.split(";",1)[1].strip(" `") if ";" in obj else ""),
        ) for
        obj in objects_clean.split("\n") if obj.split(";")[0].strip(" `\t")
    ]

    if check_errors:
        errors = []
        for obj, type, comment in objects:
            if type not in type_hierarchy.types():
                errors.append(f"Type `{type}` of object `{obj}` not found in the type hierarchy. Correct it to an existing type.")
            if obj in type_hierarchy.types():
                errors.append(f"Object `{obj}` is reusing a type name. Rename it.")
            if obj in [p["name"] for p in predicates]:
                errors.append(f"Object `{obj}` is reusing a predicate name. Rename it.")

        if errors:
            raise ValueError("\n".join([f" - {error}" for error in errors]))

    objects_str = "\n".join([f"{obj} - {type} ; {comment}" for obj, type, comment in objects])
    objects_dict = {obj: type for obj, type, _ in objects}
    return objects_dict, objects_str

def parse_state(llm_output: str, type_hierarchy: Hierarchy, predicates: list[Predicate], objects: dict[str, str], check_errors: bool = True) -> str:
    """Extract the state (PDDL-init) from the LLM output and return it as a string."""
    state_head = extract_heading(llm_output, "\n## State")
    state_raw = combine_blocks(state_head)
    state_clean = unify_comments(state_raw)

    states = []
    for line_comment in state_clean.split("\n"):
        line, comment = line_comment.split(";", 1) if ";" in line_comment else (line_comment, "")
        line = line.strip("- `()")
        if not line: # Skip empty lines
            continue
        name = line.split(" ")[0]
        if name == "not":
            neg = True
            name = line.split(" ")[1].strip("()") # Remove the `not` and the parentheses
            params = line.split(" ")[2:]
        else:
            neg = False
            params = line.split(" ")[1:] if len(line.split(" ")) > 1 else []
        states.append({"name": name, "params": params, "neg": neg, "comment": comment})

    if check_errors:
        errors = check_predicates(states, type_hierarchy, predicates, objects)
        if errors:
            raise ValueError("\n".join([f" - {error}" for error in errors]))

    inner_str = [f"({state['name']} {' '.join(state['params'])})" for state in states] # The main part of each predicate
    full_str = [f"(not {inner})" if state["neg"] else inner for state, inner in zip(states, inner_str)] # Add the `not` if needed
    comment_str = [f"{full} ; {state['comment']}" if state['comment'] else full for state, full in zip(states, full_str)] # Add the comments
    state_str = "\n".join(comment_str) # Combine the states into a single string
    return state_str

def parse_goal(llm_output: str, type_hierarchy: Hierarchy, predicates: list[Predicate], objects: dict[str, str], check_errors: bool = True) -> str:
    """Extract the goal (PDDL-goal) from the LLM output and return it as a string."""
    goal_str = extract_heading(llm_output, "\n## Goal")
    if goal_str.count("```") != 2:
        raise ValueError("Could not find exactly one block in the goal section of the LLM output. The goal has to be specified in a single block and as valid PDDL using the `and` and `not` operators. Likely this is caused by a too long response and limited context length. If so, try to shorten the message and exclude objects which aren't needed for the task.")
    goal_raw = goal_str.split("```")[1].strip() # Only a single block in the goal
    if goal_raw.lower().startswith("lisp") or goal_raw.lower().startswith("pddl"):
        goal_raw = goal_raw[4:].strip() # Remove the initial `lisp` or `pddl` from the goal
    if goal_raw.lower().startswith("markdown"):
        goal_raw = goal_raw[8:].strip() # Remove the initial `markdown` from the goal
    goal_clean = clear_comments(goal_raw)
    goal_unified = unify_comments(goal_clean)

    if check_errors:
        for keyword in ["and ", "not ", "or "]:
            for pre_char in ["(", " ", "\n", "\t"]:
                for post_char in [" ", "\n", ")"]:
                    target = pre_char + keyword + post_char
                    goal_clean = goal_clean.replace(target, "").replace(target.upper(), "")
        goals = []
        for line in goal_clean.split("\n"):
            line = line.strip(" ()")
            if not line: # Skip empty lines
                continue

            # Check for any special characters that would indicate a complex goal, we only support simple goals
            if "(" in line or ")" in line:
                break
            if "forall" in line.lower() or "exists" in line.lower() or "imply" in line.lower():
                break
            if "?" in line or "=" in line or "-" in line:
                break

            name = line.split(" ")[0]
            params = line.split(" ")[1:] if len(line.split(" ")) > 1 else []
            goals.append({"name": name, "params": params})
        else:
            # If the loop completes without breaking, check the predicates
            errors = check_predicates(goals, type_hierarchy, predicates, objects)
            if errors:
                raise ValueError("\n".join([f" - {error}" for error in errors]))

    return goal_unified # Since the goal uses `and` and `not` recombining it is difficult

def check_predicates(to_check: list[dict[str, str]], type_hierarchy: Hierarchy, predicates: list[Predicate], objects: dict[str, str]) -> list[str]:
    """
    Check the validity of predicates in a given state.

    Args:
        to_check (list[dict[str, str]]): List of states or goals to check. Each state or goal is a dictionary with "name" and "params" keys.
        predicates (list[Predicate]): List of available predicates.
        objects (dict[str, str]): Dictionary of available objects.
        type_hierarchy (Hierarchy): Object type hierarchy.

    Returns:
        list[str]: List of error messages for invalid predicates.
    """

    errors = []
    pred_names = [p["name"] for p in predicates]
    for state in to_check:
        name = state["name"]

        # Check if the predicate exists
        if name not in pred_names:
            errors.append(f"Predicate `{name}` not found. You can only use existing predicates.")
            continue
        pred = predicates[pred_names.index(name)]

        # Check if the number of objects is correct
        if len(state["params"]) != len(pred["params"]):
            errors.append(f"Predicate `{name}` expects {len(pred['params'])} objects but {len(state['params'])} were provided.")
            continue

        for i, obj in enumerate(state["params"]):
            # Check if the object exists
            if obj not in objects:
                errors.append(f"Object `{obj}` used for predicate `{name}` is not a created object. Create it if needed, or use an existing object.")
                continue

            # Check if the object is of the correct type
            type = objects[obj]
            if not type_hierarchy.is_subtype(type, list(pred["params"].values())[i]):
                errors.append(f"Object `{obj}` is not of the correct type for predicate `{name}`. `{obj}` is a `{type}` but `{name}` expects a `{list(pred['params'].values())[i]}`.")
    return errors

def clear_comments(text: str, comments = [':','//','#',';']) -> str:
    """Remove comments from the text."""
    for comment in comments:
        text = "\n".join([line.split(comment)[0] for line in text.split("\n")])
    return text

def unify_comments(text: str, comments = [':','//','#',';'], to: str = ";") -> str:
    """Unify comments in the text."""
    for comment in comments:
        text = "\n".join([line.split(comment,1)[0] + to + line.split(comment,1)[1] if comment in line else line for line in text.split("\n")])
    return text

def extract_heading(llm_output: str, heading: str):
    """Extract the text between the heading and the next second level heading in the LLM output."""
    if heading not in llm_output:
        Logger.log("#"*10, "LLM Output", "#"*10)
        Logger.log(llm_output)
        Logger.log("#"*30)
        raise ValueError(f"Could not find heading {heading} in the LLM output. Likely this is caused by a too long response and limited context length. If so, try to shorten the message and exclude objects which aren't needed for the task.")
    heading_str = llm_output.split(heading)[1].split("\n## ")[0].strip() # Get the text between the heading and the next heading
    return heading_str

def get_llm_feedback(
        llm_conn: LLM_Chat, type_hierarchy: Hierarchy, predicates: list[Predicate],
        domain_desc_str: str, objects_str: str, state_str: str, goal_str: str
    ) -> str | None:
    predicate_list = "\n".join([f"- {pred['name']}: {pred['desc']}" for pred in predicates])
    domain_file = PddlGenerator.get_domain()
    problem_file = PddlGenerator.get_problem()

    with open(os.path.join(prompt_dir, "feedback.txt")) as f:
        feedback_template = f.read().strip()
    feedback_prompt = feedback_template.replace('{objects}', objects_str)
    feedback_prompt = feedback_prompt.replace('{state}', state_str)
    feedback_prompt = feedback_prompt.replace('{goal}', goal_str)
    feedback_prompt = feedback_prompt.replace('{predicate_list}', predicate_list)
    feedback_prompt = feedback_prompt.replace('{type_hierarchy}', str(type_hierarchy))
    feedback_prompt = feedback_prompt.replace('{domain_desc}', domain_desc_str)
    feedback_prompt = feedback_prompt.replace('{domain_file}', domain_file)
    feedback_prompt = feedback_prompt.replace('{problem_file}', problem_file)

    Logger.print("Requesting feedback from LLM", subsection=False)
    feedback = llm_conn.get_response(prompt=feedback_prompt).strip()

    if "no feedback" in feedback.lower() or len(feedback.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback)
        return None
    if '"""' in feedback:
        feedback = feedback.split('"""')[1].strip()
    Logger.print("FEEDBACK:\n", feedback)

    return feedback

def problem_revision(llm_conn: LLM_Chat, revision_template: str, last_error: str | None = None):
    global REVISION_HISTORY

    if REVISION_HISTORY is None:
        problem = PddlGenerator.get_problem()
        revision_prompt = revision_template.replace('{problem}', problem)
        REVISION_HISTORY = [{'role': 'system', 'content': revision_prompt}]

    if last_error is not None:
        error_prompt = f'# Error\nThe above problem file could not be parsed due to the following error(s). Start by addressing the cause of this error(s) under a "# Error Analysis" header. Then provide a corrected version within a markdown code block under the "# Domain" header.\n\n{last_error}\n\n# Error Analysis'
        REVISION_HISTORY.append({'role': 'user', 'content': error_prompt})

    messages = shorten_messages(REVISION_HISTORY)

    Logger.print("Requesting revision from LLM", subsection=False)
    response = llm_conn.get_response(messages=messages).strip()
    REVISION_HISTORY.append({'role': 'assistant', 'content': response})

    if "```" in response:
        new_problem = response.split("```")[1].strip().lower()
        # Make sure domain name is what we want, and remove any initial comments (i.e. markdown, pddl, lisp)
        if "(:objects" in new_problem:
            problem_header = f"(define (problem {PddlGenerator.domain}_problem) (:domain {PddlGenerator.domain})\n"
            problem_body = f"(:objects {new_problem.split('(:objects', maxsplit=1)[1]}\n"
            new_problem = problem_header + problem_body
        else:
            Logger.print("WARNING: Could not find the problem section in the revised problem. Attempting to use the full response.")

        Logger.print("New problem:\n```\n", new_problem, "\n```\n")
        PddlGenerator.overwrite_problem(new_problem)
        return new_problem
    else:
        Logger.print("No new problem received")
        return None