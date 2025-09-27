from collections import OrderedDict
import os, re, itertools, copy
from typing import Literal

from .utils.pddl_output_utils import parse_new_predicates, parse_params, combine_blocks, remove_comments
from .utils.pddl_types import Predicate, Action
from .utils.paths import action_construction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.human_feedback import human_feedback
from .utils.pddl_syntax_validator import PDDL_Syntax_Validator
from .utils.pddl_errors import domain_errors
from .hierarchy_construction import Hierarchy
from .utils.llm_model import LLM_Chat, get_llm, shorten_messages

MESSAGE_HISTORY = {}
REVISION_HISTORY = None

@Logger.section("4 Action Construction")
def action_construction(
        llm_conn: LLM_Chat,
        action_descs: dict[str, str],
        domain_desc_str: str,
        type_hierarchy: Hierarchy,
        unsupported_keywords: list[str] | None = None,
        feedback: str | None = None,
        max_attempts: int = 8,
        shorten_message: bool = False,
        max_iters: int = 2,
        mirror_symmetry: bool = False,
        generalize_predicate_types: bool = False,
        feedback_level: Literal["domain", "action", "both"] = "domain",
        revise_domain_iters: int = 0,
    ) -> tuple[list[Action], list[Predicate]]:
    """
    Construct actions from a given domain description using an LLM_Chat language model.

    Args:
        llm_conn (LLM_Chat): The LLM_Chat language model connection.
        actions (dict[str, str]): A dictionary of actions to construct, where the keys are action names and the values are action descriptions.
        domain_desc_str (str): The domain description string.
        type_hierarchy (Hierarchy): The type hierarchy.
        unsupported_keywords (list[str]): A list of unsupported keywords.
        feedback (bool): Whether to request feedback from the language model. Defaults to True.
        max_attempts (int): The maximum number of messages to send to the language model. Defaults to 8.
        shorten_message (bool): Whether to shorten the messages sent to the language model. Defaults to False.
        max_iters (int): The maximum number of iterations to construct each action. Defaults to 2.
        mirror_symmetry (bool): Whether to mirror any symmetrical predicates used process. Defaults to False.
        generalize_predicate_types (bool): Whether to allow generalization of predicate types after creation. Defaults to False.
        feedback_level (str): The level of feedback to request from the language model. Defaults to "domain".
        revise_domain_iters (int): The maximum number of iterations to revise the domain. Defaults to 4.

    Returns:
        list[Action]: A list of constructed actions.
        list[Predicate]: A list of predicates.
    """
    global MESSAGE_HISTORY
    MESSAGE_HISTORY = {} # Reset the message history

    llm_conn.reset_token_usage()
    action_feedback = feedback if (feedback_level == "action" or feedback_level == "both") else None
    domain_feedback = feedback if (feedback_level == "domain" or feedback_level == "both") else None
    received_domain_feedback = None

    action_list = "\n".join([f"- {name}: {desc}" for name, desc in action_descs.items()])

    with open(os.path.join(prompt_dir, "main.txt")) as f:
        act_constr_template = f.read().strip()
    act_constr_template = act_constr_template.replace('{domain_desc}', domain_desc_str)
    act_constr_template = act_constr_template.replace('{type_hierarchy}', str(type_hierarchy))
    act_constr_template = act_constr_template.replace('{action_list}', action_list)

    with open(os.path.join(prompt_dir, "action_feedback.txt")) as f:
        action_feedback_template = f.read().strip()
    action_feedback_template = action_feedback_template.replace('{domain_desc}', domain_desc_str)
    action_feedback_template = action_feedback_template.replace('{type_hierarchy}', str(type_hierarchy))
    action_feedback_template = action_feedback_template.replace('{action_list}', action_list)

    with open(os.path.join(prompt_dir, "domain_feedback.txt")) as f:
        domain_feedback_template = f.read().strip()
    domain_feedback_template = domain_feedback_template.replace('{domain_desc}', domain_desc_str)
    domain_feedback_template = domain_feedback_template.replace('{type_hierarchy}', str(type_hierarchy))
    domain_feedback_template = domain_feedback_template.replace('{action_list}', action_list)

    with open(os.path.join(prompt_dir, "domain_revision.txt")) as f:
        domain_revision_template = f.read().strip()
    domain_revision_template = domain_revision_template.replace('{domain_desc}', domain_desc_str.replace("\n", "\n> "))

    syntax_validator = PDDL_Syntax_Validator(type_hierarchy, unsupported_keywords=unsupported_keywords)

    predicates = []
    for iter in range(max_iters):
        actions = []
        Logger.print(f"Starting iteration {iter + 1} of action construction", subsection=False)
        ingoing_pred = copy.deepcopy(predicates)
        for action_name, action_desc in action_descs.items():

            if received_domain_feedback is not None and received_domain_feedback.get(action_name,None) is None:
                Logger.print("No feedback received for action '", action_name, "'. Retaining last version.", subsection=False)
                idx = [a["name"] for a in actions_before_feedback].index(action_name)
                action = actions_before_feedback[idx]
                actions.append(action)
                continue

            action, new_predicates, to_generalize = construct_action(
                llm_conn, act_constr_template, action_name, action_desc, predicates, syntax_validator, action_feedback_template,
                max_iters=max_attempts, feedback=action_feedback, shorten_message=shorten_message, mirror_symmetry=mirror_symmetry,
                generalize_predicate_types=generalize_predicate_types, domain_feedback = received_domain_feedback, type_hierarchy=type_hierarchy
            )
            actions.append(action)
            predicates = join_and_generalize_predicates(predicates, new_predicates, to_generalize if generalize_predicate_types else {})

        if domain_feedback and iter < max_iters - 1:
            actions_before_feedback = copy.deepcopy(actions)
            received_domain_feedback = get_domain_feedback(llm_conn, domain_feedback_template, predicates, actions)
            if received_domain_feedback is None:
                Logger.print("No feedback received. Stopping action construction.", subsection=False)
                break
            continue
        if not any([p['name'] not in [pred['name'] for pred in ingoing_pred] for p in predicates]):
            Logger.print("No new predicates created. Stopping action construction.", subsection=False)
            break
    else:
        Logger.print("Reached maximum iterations. Stopping action construction.", subsection=False)

    predicates = prune_predicates(predicates, actions) # Remove predicates that are not used in any action
    types = type_hierarchy.types()
    pruned_types = prune_types(types, predicates, actions) # Remove types that are not used in any predicate or action

    Logger.print("Constructed actions:\n", "\n\n".join([
        str(action) \
            .replace("'name':",             "\n\t'name':") \
            .replace("'parameters':",       "\n\t'parameters':") \
            .replace("'preconditions':",    "\n\t'preconditions':") \
            .replace("'effects':",          "\n\t'effects':") \
            .replace("}", "\n}")
        for action in actions
    ]))
    setup_domain(actions, predicates)

    global REVISION_HISTORY # Reset the revision history
    REVISION_HISTORY = None
    domain_revision_error = None
    while revise_domain_iters > 0:
        revise_domain_iters -= 1

        revisions = domain_revision(llm_conn, domain_revision_template, predicates, actions, domain_revision_error)

        errors = domain_errors(PddlGenerator.domain_file)
        if errors is not None:
            Logger.print(f"Failed to parse revised domain:\n{errors}. Retrying iteration {revise_domain_iters}.", subsection=False)
            domain_revision_error = errors
            continue

        if revisions is not None:
            revised_predicates, revised_types = revisions
            Logger.print("REVISED PREDICATES: ", revised_predicates)
            Logger.print("REVISED TYPES: ", revised_types)
            predicates = revised_predicates
            type_hierarchy.overwrite_from_dicts(*revised_types)
            Logger.print("REVISED TYPE HIERARCHY: ", type_hierarchy)
            pruned_types = type_hierarchy.types()
        break

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Action_Construction_Tokens=(in_tokens, out_tokens))

    return actions, predicates, pruned_types

def construct_action(
        llm_conn: LLM_Chat,
        act_constr_prompt: str,
        action_name: str,
        action_desc: str,
        predicates: list[Predicate],
        syntax_validator: PDDL_Syntax_Validator,
        feedback_template: str = None,
        max_iters=8,
        shorten_message=False,
        feedback=True,
        mirror_symmetry=False,
        generalize_predicate_types=False,
        domain_feedback = None,
        type_hierarchy: Hierarchy = None
    ) -> tuple[Action, list[Predicate], dict[str, dict[int, str]]]:
    """
    Construct an action from a given action description using a LLM_Chat language model.

    Args:
        llm_conn (LLM_Chat): The LLM_Chat language model connection.
        act_constr_prompt (str): The action construction prompt.
        action_name (str): The name of the action.
        action_desc (str): The action description.
        predicates list[Predicate]: A list of predicates.
        syntax_validator (PDDL_Syntax_Validator): The PDDL syntax validator.
        feedback_template (str): The feedback template. Has to be specified if feedback used. Defaults to None.
        max_iters (int): The maximum number of iterations to construct the action. Defaults to 8.
        shorten_message (bool): Whether to shorten the messages sent to the language model. Defaults to False.
        feedback (bool): Whether to request feedback from the language model. Defaults to True.
        mirror_symmetry (bool): Whether to mirror any symmetrical predicates in the action preconditions. Defaults to False.
        generalize_predicate_types (bool): Whether to allow generalization of predicate types after creation. Defaults to False.
        domain_feedback (dict[str,str]): The domain feedback. Defaults to None.

    Returns:
        Action: The constructed action.
        new predicates list[Predicate]: A list of new predicates.
    """
    global MESSAGE_HISTORY

    if max_iters < 1:
        raise ValueError("The maximum number of attempts during Action Construction (step 4) must be at least 1.")

    act_constr_prompt = act_constr_prompt.replace('{action_desc}', action_desc)
    act_constr_prompt = act_constr_prompt.replace('{action_name}', action_name)
    if len(predicates) == 0:
        predicate_str = "No predicate has been defined yet"
    else:
        predicate_str = ""
        for i, pred in enumerate(predicates): predicate_str += f"{i+1}. {pred['signature']}: {pred['desc']}\n"
    act_constr_prompt = act_constr_prompt.replace('{predicate_list}', predicate_str)

    messages = MESSAGE_HISTORY.get(action_name, [{'role': 'user', 'content': act_constr_prompt}])

    if feedback_template is not None:
        feedback_template = feedback_template.replace('{action_desc}', action_desc)
        feedback_template = feedback_template.replace('{action_name}', action_name)
    elif feedback:
        raise ValueError("Feedback template is required when feedback is enabled.")

    if domain_feedback is not None and domain_feedback[action_name] is not None:
        with open(os.path.join(prompt_dir, "error.txt")) as f:
            error_template = f.read().strip()
        domain_feedback_prompt = error_template.replace('{action_name}', action_name)
        domain_feedback_prompt = domain_feedback_prompt.replace('{action_desc}', action_desc)
        domain_feedback_prompt = domain_feedback_prompt.replace('{predicate_list}', predicate_str)
        domain_feedback_prompt = domain_feedback_prompt.replace('{error_msg}', domain_feedback[action_name])
        messages += [{'role': 'user', 'content': domain_feedback_prompt}]

    received_feedback_at = None
    for iter in range(1, max_iters + 1 + (feedback is not None)):
        Logger.print(f'Generating PDDL of action: `{action_name}` | # of messages: {len(messages)}', subsection=False)

        msgs_to_send = messages if not shorten_message else shorten_messages(messages)
        llm_output = llm_conn.get_response(prompt=None, messages=msgs_to_send)
        messages.append({'role': 'assistant', 'content': llm_output})

        try:
            llm_output = clean_llm_output(llm_output)
            new_predicates = parse_new_predicates(llm_output, type_hierarchy)
            validation_info = syntax_validator.perform_validation(
                llm_output, curr_predicates = predicates, new_predicates = new_predicates,
                generalize_predicate_types = "allow" if generalize_predicate_types else "dissallow" # Allow generalization if the flag is set
            )
            no_error, error_type, _, error_msg = validation_info

            # Check with real parsers
            # Start by parsing the action
            action = parse_action(llm_output, action_name, action_desc) # Check if the action can be parsed
            # Then, parse the new and generalized predicates
            new_predicates = [pred for pred in new_predicates if pred['name'] not in [p["name"] for p in predicates]]
            if generalize_predicate_types and not (action["preconditions"] == "" and action["effects"] == ""):
                predicates_to_generalize = syntax_validator.check_predicate_usage(
                    llm_output=llm_output, curr_predicates = predicates, new_predicates = new_predicates,
                    generalize_predicate_types="return"
                )
            else:
                predicates_to_generalize = {}
            joint_predicates = generalize_predicates(predicates + new_predicates, predicates_to_generalize)
            # Finally, create a domain with the new action and validate it
            sad = PddlGenerator.single_action_domain(action, joint_predicates) # Create a domain with the new action
            dom_error_msg = domain_errors(sad) # Check if the action can be parsed by proper parsers
            Logger.log(f"SAD:\n{open(sad).read()}", subsection=True)
            Logger.log(f"ERROR_MSG: {dom_error_msg}", subsection=False)
            if dom_error_msg is not None:
                no_error = False
                error_type = "domain_validation_fail" if error_type == "all_validation_pass" else error_type + " and domain_validation_fail"
                error_msg = dom_error_msg if error_msg is None else error_msg + "\n\n" + dom_error_msg
            # Delete the sad
            os.remove(sad)

        except Exception as e:
            # If it's an IndexError, we pass it on
            if str(e.__class__.__name__) == "IndexError":
                raise e
            # If it's a key error, we pass it on
            if str(e.__class__.__name__) == "KeyError":
                raise e
            # IF it's a type error, we pass it on
            if str(e.__class__.__name__) == "TypeError":
                raise e
            no_error = False
            error_msg = str(e)
            error_type = str(e.__class__.__name__)

        if iter == max_iters + (feedback is not None):
            continue # No space for further iterations, so we skip the validation

        if no_error or error_type == "all_validation_pass":
            if received_feedback_at is None and feedback is not None:
                received_feedback_at = iter
                error_type = "feedback"
                if feedback.lower() == "human":
                    action = parse_action(llm_output, action_name, action_desc)
                    new_predicates = parse_new_predicates(llm_output, type_hierarchy)
                    preds = "\n".join([f"\t- {pred['clean']}" for pred in new_predicates])
                    msg  = f"\n\nThe action {action_name} has been constructed.\n\n"
                    msg += f"Action desc: \n\t{action_desc}\n\n"
                    msg += f"Parameters: \n\t{action['parameters']}\n\n"
                    msg += f"Preconditions: \n{action['preconditions']}\n\n"
                    msg += f"Effects: \n{action['effects']}\n\n"
                    msg += f"New predicates: \n{preds}\n"
                    error_msg = human_feedback(msg)
                else:
                    error_msg = get_llm_feedback(llm_conn, feedback_template, llm_output, predicates, new_predicates)
                if error_msg is None:
                    break # No feedback and no error, so we can stop iterating
            else:
                break # No error and feedback finished, so we can stop iterating

        Logger.print(f"Error of type {error_type} for action {action_name} iter {iter}:\n{error_msg}", subsection=False)

        with open(os.path.join(prompt_dir, "error.txt")) as f:
            error_template = f.read().strip()
        error_prompt = error_template.replace('{action_name}', action_name)
        error_prompt = error_prompt.replace('{action_desc}', action_desc)
        error_prompt = error_prompt.replace('{predicate_list}', predicate_str)
        error_prompt = error_prompt.replace('{error_msg}', error_msg)

        messages.append({'role': 'user', 'content': error_prompt})
    else:
        Logger.print(f"Reached maximum iterations. Stopping action construction for {action_name}.", subsection=False)

    try:
        action = parse_action(llm_output, action_name, action_desc)
        new_predicates = parse_new_predicates(llm_output, type_hierarchy)
        new_predicates = prune_predicates(new_predicates, [action]) # Remove newly defined predicates that aren't actually used
    except Exception as e:
        Logger.print(f"Failed to parse action {action_name} or its predicates:\n{str(e)}. Returning empty action.", subsection=False)
        action = {"name": action_name, "parameters": {}, "preconditions": "", "effects": "", "desc": action_desc}
        new_predicates = []
    # Remove re-defined predicates
    unique_new_predicates = [pred for pred in new_predicates if pred['name'] not in [p["name"] for p in predicates]]

    if mirror_symmetry:
        action = mirror_action(action, predicates + new_predicates)

    if generalize_predicate_types and not (action["preconditions"] == "" and action["effects"] == ""):
        predicates_to_generalize = syntax_validator.check_predicate_usage(
            llm_output=llm_output, curr_predicates = predicates, new_predicates = unique_new_predicates,
            generalize_predicate_types="return"
        )
    else:
        predicates_to_generalize = {}

    MESSAGE_HISTORY[action_name] = messages # Save the message history for this action in case we need to revise it
    return action, new_predicates, predicates_to_generalize

def join_and_generalize_predicates(old_predicates: list[Predicate], new_predicates: list[Predicate], to_generalize: dict) -> list[Predicate]:
    # If a predicate is redefined with the same parameters, we keep the new description
    new_types = {pred['name']: [t for p, t in pred['params'].items()] for pred in new_predicates}
    old_types = {pred['name']: [t for p, t in pred['params'].items()] for pred in old_predicates}

    predicates = []
    for o_pred in old_predicates:
        if o_pred['name'] in new_types and new_types[o_pred['name']] == old_types[o_pred['name']]:
            # The predicate is redefined with the same parameters. We keep the new description
            predicates.append(o_pred)
        else:
            # The predicate is not redefined or the parameters have changed. We keep the old description
            predicates.append(o_pred)

    for n_pred in new_predicates:
        if n_pred['name'] not in old_types:
            # The predicate is new. We keep the new description
            predicates.append(n_pred)

    if len(to_generalize) > 0:
        # Generalize the types of the predicates based on the most recent action
        predicates = generalize_predicates(predicates, to_generalize)

        # Now we re-check if any of the new predicates are redefined with the new generalized parameters
        old_predicates = predicates
        old_types = {pred['name']: [t for p, t in pred['params'].items()] for pred in old_predicates}

        predicates = []
        for o_pred in old_predicates:
            if o_pred['name'] in new_types and new_types[o_pred['name']] == old_types[o_pred['name']]:
                # The predicate is redefined with the same parameters. We keep the new description
                predicates.append(o_pred)
            else:
                # The predicate is not redefined or the parameters have changed. We keep the old description
                predicates.append(o_pred)

    return predicates

def get_domain_feedback(llm_conn: LLM_Chat, feedback_template: str, predicates: list[Predicate], actions: list[Action]) -> dict[str,str] | None:
    """
    Get domain feedback from the language model.

    Args:
        llm_conn (LLM_Chat): The LLM_Chat language model connection.
        feedback_template (str): The feedback template.
        predicates (list[Predicate]): A list of predicates.
        actions (list[Action]): A list of actions.

    Returns:
        dict[str,str]: The domain feedback.
    """
    domain = setup_domain(actions, predicates)
    domain = remove_comments(domain, skip_pddl_header=True) # Remove comments from the domain, they can be misleading
    feedback_prompt = feedback_template.replace('{domain}', domain)

    action_list = "\n".join([f"**{action['name']}**\n{action['desc']}" for action in actions])
    feedback_prompt = feedback_prompt.replace('{action_list}', action_list)

    response = llm_conn.get_response(prompt=feedback_prompt).strip()

    feedback = {a["name"]: None for a in actions}
    for action in actions:
        Logger.print("\n\nChecking feedback for action '", action["name"], "'", subsection=False)
        if not (f"\n### {action['name']}\n" in response or f"\n#### {action['name']}\n" in response):
            Logger.print(f"Could not find section for action '{action['name']}'", subsection=False)
            continue
        if f"\n### {action['name']}\n" in response:
            section = response.split(f"\n### {action['name']}\n")[1].split("## ")[0].strip(" \n#\t")
        else:
            section = response.split(f"\n#### {action['name']}\n")[1].split("## ")[0].strip(" \n#\t")
        Logger.log(f"Found section for action '{action['name']}':\n{section}\n", subsection=False)
        if "no feedback" in section.lower():
            Logger.print(f"Feedback for action '{action['name']}' is 'no feedback'", subsection=False)
            continue
        feedback[action['name']] = section.strip()
        Logger.print(f"Feedback for action '{action['name']}':\n{feedback[action['name']]}", subsection=False)

    if any([f is not None for f in feedback.values()]):
        Logger.print("Returning feedback")
        return feedback
    Logger.print("No feedback received")
    return None

def domain_revision(llm_conn: LLM_Chat, revision_template: str, predicates: list[Predicate], actions: list[Action], last_error: str | None) -> list[Predicate] | None:
    global REVISION_HISTORY

    if REVISION_HISTORY is None:
        domain = setup_domain(actions, predicates)
        revision_prompt = revision_template.replace('{domain}', domain)
        REVISION_HISTORY = [{'role': 'system', 'content': revision_prompt}]

    if last_error is not None:
        error_prompt = f'# Error\nThe above domain description could not be parsed due to the following error(s). Start by addressing the cause of this error(s) under a "# Error Analysis" header. Then provide a corrected version within a markdown code block under the "# Domain" header.\n\n{last_error}\n\n# Error Analysis'
        REVISION_HISTORY.append({'role': 'user', 'content': error_prompt})

    messages = shorten_messages(REVISION_HISTORY)

    Logger.print("Requesting revision from LLM", subsection=False)
    response = llm_conn.get_response(messages=messages).strip()
    REVISION_HISTORY.append({'role': 'assistant', 'content': response})

    if "```" in response:
        if "# Domain" in response:
            new_domain = response.split("# Domain")[1].split("```")[1].strip().lower()
        else:
            new_domain = response.split("```")[1].strip().lower()
        # Make sure domain name is what we want, and remove any initial comments (i.e. markdown, pddl, lisp)
        if "(:requirements" in new_domain:
            domain_header = f"(define (domain {PddlGenerator.domain})\n\t"
            domain_body = f"(:requirements {new_domain.split('(:requirements',maxsplit=1)[1].strip()}"
            new_domain = domain_header + domain_body
        else:
            Logger.print("WARNING: Could not find domain header in revised domain. Attempting to use the entire domain.")

        Logger.print("New domain:\n```\n", new_domain, "\n```\n")
        PddlGenerator.overwrite_domain(new_domain)
        return parse_revised_predicates(new_domain, predicates), parse_revised_types(new_domain)
    else:
        Logger.print("No new domain received")
        return None

def parse_revised_predicates(domain: str, predicates: list[Predicate]) -> list[Predicate]:
    """
    Parse the revised predicates from a given domain.

    Args:
        domain (str): The domain.

    Returns:
        list[Predicate]: The revised predicates.
    """
    revised_predicates = []
    lingering_desc = ""
    for pred in domain.split("(:predicates")[1].split("(:action")[0].split("\n"):
        pred = pred.strip(" ()\n")
        if pred == "":
            continue
        name = pred.split(";")[0].split(" ")[0].strip()
        if name == "":
            # If the row is only a description, we remember the description and add it to the next predicate
            lingering_desc += pred.split(";")[1].strip()
            continue
        args = pred[len(name):].split(";")[0].strip(" ()\n")
        #Logger.print(f"PREDICATE: '{pred}'. NAME: '{name}'. ARGS: '{args}'",subsection=False)
        params, i = OrderedDict(), 0
        while i < len(args.split(" ")) and len(args) > 0:
            Logger.print(f"   I: '{i}'.ARGS: '{args}'. SPLIT: '{args.split(' ')}'.",subsection=False)
            p = args.split(" ")[i].strip()
            if args.split(" ")[i+1].strip() != "-":
                Logger.print(f"Error parsing predicate '{name}': Expected '-' after parameter '{p}'. Attempting to retain existing predicate.")
                for old_pred in predicates:
                    if old_pred['name'] == name:
                        params = old_pred['params']
                        break
                else:
                    # If no existing predicate is found, we skip this predicate
                    Logger.print(f"Could not find existing predicate '{name}'. Skipping this predicate.")
                    break
            t = args.split(" ")[i+2].strip()
            params[p] = t
            i += 3
        else:
            # If the loop completes without breaking, the parameters have been successfully parsed
            desc  = lingering_desc
            desc += pred.split(";")[1].strip() if ";" in pred else ""
            lingering_desc = ""

            signature = f"({name} - {', '.join([f'{k} - {v}' for k, v in params.items()])})"

            revised_predicates.append({
                "name": name,
                "desc": desc,
                "raw": pred,
                "params": params,
                "clean": signature + f": {desc}",
                "signature": signature,
            })
    return revised_predicates

def parse_revised_types(domain: str) -> list[str]:
    """
    Parse the revised types from a given domain.

    Args:
        domain (str): The domain.
        types (list[str]): The types.

    Returns:
        list[str]: The revised types.
    """
    revised_types = {"object": None}
    revised_descs = {"object": "Object is always root, everything is an object"}
    lingering_desc = ""

    for line in domain.split("(:types")[1].split("(:predicates")[0].split("\n"):
        line = line.strip(" ()\n")
        if line == "":
            continue
        if line.startswith(";"):
            lingering_desc += line.strip(";")
            continue
        Logger.print(f"LINE: '{line}'")
        info = line.split(";")[0].strip()
        desc = lingering_desc + line.split(";")[1].strip() if ";" in line else ""
        type = info.split(" ")[0].strip()
        parent = info.split(" ")[2].strip() if len(info.split(" ")) > 2 else "object"
        revised_types[type] = parent
        revised_descs[type] = desc
        lingering_desc = ""
    return revised_types, revised_descs

def setup_domain(actions: list[Action], predicates: list[Predicate]):
    PddlGenerator.reset_actions()
    for action in actions:
        PddlGenerator.add_action(action)
    predicate_str = "\n".join([pred["clean"].replace(":", " ; ",1) for pred in predicates])
    PddlGenerator.set_predicates(predicate_str)
    predicate_str = predicate_str.replace("\n", "\n\n") # Add extra newline for better readability
    domain, _ = PddlGenerator.generate()
    return domain

def parse_action(llm_output: str, action_name: str, action_desc: str) -> Action:
    """
    Parse an action from a given LLM output.

    Args:
        llm_output (str): The LLM output.
        action_name (str): The name of the action.

    Returns:
        Action: The parsed action.
    """
    parameters = parse_params(llm_output)
    try:
        preconditions = llm_output.split("Preconditions\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Preconditions' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    try:
        effects = llm_output.split("Effects\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Effects' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    return {"name": action_name, "parameters": parameters, "preconditions": preconditions, "effects": effects, "desc": action_desc}

def get_llm_feedback(llm_conn: LLM_Chat, feedback_template: str, llm_output: str, predicates: list[Predicate], new_predicates: list[Predicate]) -> str | None:
    all_predicates = predicates + [pred for pred in new_predicates if pred['name'] not in [p["name"] for p in predicates]]
    action_params = combine_blocks(llm_output.split("Parameters")[1].split("##")[0])
    action_preconditions = llm_output.split("Preconditions")[1].split("##")[0].split("```")[1].strip(" `\n")
    action_effects = llm_output.split("Effects")[1].split("##")[0].split("```")[-2].strip(" `\n")
    predicate_list = "\n".join([f"- {pred['name']}: {pred['desc']}" for pred in all_predicates])

    feedback_prompt = feedback_template.replace('{action_params}', action_params)
    feedback_prompt = feedback_prompt.replace('{action_preconditions}', action_preconditions)
    feedback_prompt = feedback_prompt.replace('{action_effects}', action_effects)
    feedback_prompt = feedback_prompt.replace('{predicate_list}', predicate_list)

    Logger.print("Requesting action feedback from LLM", subsection=False)
    feedback = llm_conn.get_response(prompt=feedback_prompt).strip()
    if "no feedback" in feedback.lower() or len(feedback.strip()) == 0:
        Logger.print(f"No Received feedback:\n {feedback}")
        return None

    return feedback

def prune_predicates(predicates: list[Predicate], actions: list[Action]) -> list[Predicate]:
    """
    Remove predicates that are not used in any action.

    Args:
        predicates (list[Predicate]): A list of predicates.
        actions (list[Action]): A list of actions.

    Returns:
        list[Predicate]: The pruned list of predicates.
    """
    used_predicates = []
    for pred in predicates:
        for action in actions:
            # Add a space or a ")" to avoid partial matches
            names = [f"({pred['name']} ", f"({pred['name']})", f"( {pred['name']} "]
            for name in names:
                if name in action['preconditions'] or name in action['effects']:
                    used_predicates.append(pred)
                    Logger.log(f"Predicate '{pred['name']}' is used in action '{action['name']}'", subsection=False)
                    break
            else: # If the predicate is not used in this action, check the next action
                continue
            break # If the predicate is used in this action, skip checking the rest of the actions
    return used_predicates

def generalize_predicates(predicates: list[Predicate], to_generalize: dict[str, dict[int, str]]) -> list[Predicate]:
    """
    Generalize the types of the predicates based on the most recent action
    """
    if len(to_generalize) == 0:
        # No predicates to generalize. Keep the predicates as they are
        return predicates
    Logger.print("TO GENERALIZE:", to_generalize)
    general = []
    for pred in predicates:
        if pred["name"] in to_generalize:
            general.append(generalize_predicate(pred, to_generalize[pred["name"]]))
            Logger.print(f"Generalizing predicate {pred['name']}:\n{pred['signature']} -> {general[-1]['signature']}")
        else:
            general.append(pred)
    return general

def generalize_predicate(predicate, generalization):
    if len(generalization) == 0:
        return predicate
    note = " Note that The type of the following parameter(s) has been updated  "
    if not predicate["desc"].endswith("."):
        note = "." + note
    new_signature = predicate["signature"]
    curr_types = list(predicate["params"].items())
    for i, new_type in generalization.items():
        new_signature = new_signature.replace(
            f"{curr_types[i][0]} - {curr_types[i][1]}",
            f"{curr_types[i][0]} - {new_type}",
        )
        note += f"{curr_types[i][0]} -> {new_type}, "
    note = note[:-2] + "." # Remove the last comma
    return {
        "name": predicate["name"],
        "desc": predicate["desc"] + note,
        "params": {k: generalization.get(i, v) for i, (k, v) in enumerate(predicate["params"].items())},
        "clean": new_signature + f": {predicate['desc']}" + note,
        "signature": new_signature,
    }

def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    return llm_output

def mirror_action(action: Action, predicates: list[Predicate]):
    """
    Mirror any symmetrical predicates used in the action preconditions.

    Example:
        Original action:
        (:action drive
            :parameters (
                ?truck - truck
                ?from - location
                ?to - location
            )
            :precondition
                (and
                    (at ?truck ?from)
                    (connected ?to ?from)
                )
            :effect
                (at ?truck ?to )
            )
        )

        Mirrored action:
        (:action drive
            :parameters (
                ?truck - truck
                ?from - location
                ?to - location
            )
            :precondition
                (and
                    (at ?truck ?from)
                    ((connected ?to ?from) or (connected ?from ?to))
                )
            :effect
                (at ?truck ?to )
            )
        )
    """
    mirrored = copy.deepcopy(action)
    for pred in predicates:
        if pred["name"] not in action["preconditions"]:
            continue # The predicate is not used in the preconditions
        param_types = list(pred["params"].values())
        for type in set(param_types):
            # For each type
            if not param_types.count(type) > 1:
                continue # The type is not repeated
            # The type is repeated
            occs = [i for i, x in enumerate(param_types) if x == type]
            perms = list(itertools.permutations(occs))
            if len(occs) > 2:
                Logger.print(f"[WARNING] Mirroring predicate with {len(occs)} occurences of {type}.", subsection=False)
            uses = re.findall(f"\({pred['name']}.*\)", action["preconditions"]) # Find all occurrences of the predicate used in the preconditions
            for use in uses:
                versions = [] # The different versions of the predicate
                args = [use.strip(" ()").split(" ")[o+1] for o in occs] # The arguments of the predicate
                template = use
                for i, arg in enumerate(args): # Replace the arguments with placeholders
                    template = template.replace(arg, f"[MIRARG{i}]", 1)
                for perm in perms:
                    ver = template
                    for i, p in enumerate(perm):
                        # Replace the placeholders with the arguments in the permutation
                        ver = ver.replace(f"[MIRARG{i}]", args[p])
                    if ver not in versions:
                        versions.append(ver) # In case some permutations are the same (repeated args)
                combined = "(" + " or ".join(versions) + ")"
                mirrored["preconditions"] = mirrored["preconditions"].replace(use, combined)
    return mirrored

def prune_types(types: list[str], predicates: list[Predicate], actions: list[Action]):
    """
    Prune types that are not used in any predicate or action.

    Args:
        types (list[str]): A list of types.
        predicates (list[Predicate]): A list of predicates.
        actions (list[Action]): A list of actions.

    Returns:
        list[str]: The pruned list of types.
    """
    used_types = []
    for type in types:
        for pred in predicates:
            if type in pred['params'].values():
                used_types.append(type)
                break
        else:
            for action in actions:
                if type in action['parameters'].values():
                    used_types.append(type)
                    break
                if type in action['preconditions'] or type in action['effects']: # If the type is included in a "forall" or "exists" statement
                    used_types.append(type)
                    break
    return used_types
