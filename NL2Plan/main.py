import os, pickle
from typing import Literal

from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator

from .utils.llm_model import get_llm
from .hierarchy_construction import hierarchy_construction
from .type_extraction import type_extraction
from .stream_extraction import stream_extraction
from .stream_construction import stream_construction
from .problem_extraction import problem_extraction
from .planning import planning

def main(
        domain_name: str,
        domain_task: str,
        engine: str,
        act_constr_iters: int = 2,
        act_constr_feedback_level: Literal["domain", "action", "both"] = "domain",
        max_step_4_attempts: int = 5,
        max_step_5_attempts: int = 5,
        max_step_6_attempts: int = 5,
        feedback: str | None = None,
        checkpoints: bool = False,
        start_from: int = 1,
        start_dir: str = None,
        end_after: int = 6,
        instance_name: str = None,
        shorten_message: bool = True, # Changing this is not fully supported
        generalize_predicates: bool = True, # Changing this is not fully supported
        validation_enabled: bool = True,
    ) -> list[str] | None:
    Logger.start(
        domain_name,
        domain_desc_task = domain_task,
        engine=engine,
        act_constr_iters=act_constr_iters,
        act_constr_feedback_level=act_constr_feedback_level,
        max_step_4_attempts=max_step_4_attempts,
        max_step_5_attempts=max_step_5_attempts,
        max_step_6_attempts=max_step_6_attempts,
        feedback=feedback,
        checkpoints=checkpoints,
        start_from=start_from,
        start_dir=start_dir,
        end_after=end_after,
        instance_name=instance_name,
        shorten_message=shorten_message,
        generalize_predicates=generalize_predicates,
        validation_enabled=validation_enabled
    )
    if start_dir is None and start_from > 1:
        raise ValueError("Start path must be provided if starting from a checkpoint.")
    if max_step_4_attempts < 1:
        raise ValueError("The maximum number of attempts during Action Construction (step 4) must be at least 1.")
    if max_step_5_attempts < 1:
        raise ValueError("The maximum number of attempts during Problem Extraction (step 5) must be at least 1.")

    # init PDDL generator
    PddlGenerator.start()

    # init LLM
    llm_gpt = get_llm(engine=engine)

    # extract domain info
    Logger.add_domain_desc(domain_task)

    # extract the available types
    if start_from <= 1:
        init = type_extraction(llm_gpt, domain_task, feedback=feedback)
        PddlGenerator.generate()

    """
        if checkpoints:
            with open(f"{Logger.directory}/checkpoint1.pkl", 'wb') as f:  # Open the file in binary mode
                pickle.dump([types, PddlGenerator], f)  # Write the data as bytes
    elif start_from == 2:
        with open(os.path.join(start_dir, "checkpoint1.pkl"), 'rb') as f:
            types, PddlGenerator2 = pickle.load(f)
        PddlGenerator.copy(PddlGenerator2)
    if end_after <= 1:
        PddlGenerator.generate() # Generate the final PDDL file
        return None
        """

    """
    if start_from <= 2:
        # construct the type hierarchy
        type_hierarchy = hierarchy_construction(
            llm_gpt, types, domain_desc=domain_task, replace_comments=True,
            feedback=feedback, prune=True,
        )
        PddlGenerator.generate()

        if checkpoints:
            with open(f"{Logger.directory}/checkpoint2.pkl", 'wb') as f:
                pickle.dump([types, type_hierarchy, PddlGenerator], f)
    elif start_from == 3:
        with open(os.path.join(start_dir, "checkpoint2.pkl"), 'rb') as f:
            types, type_hierarchy, PddlGenerator2 = pickle.load(f)
        PddlGenerator.copy(PddlGenerator2)
    if end_after <= 2:
        PddlGenerator.generate()
        return None
    """

    # extract action info
    if start_from <= 3:
        stream_desc = stream_extraction(llm_gpt, domain_task, init, feedback=feedback)
        PddlGenerator.generate()

        if checkpoints:
            with open(f"{Logger.directory}/checkpoint3.pkl", 'wb') as f:
                pickle.dump([stream_desc, PddlGenerator], f)
    elif start_from == 4:
        with open(os.path.join(start_dir, "checkpoint3.pkl"), 'rb') as f:
            types, type_hierarchy, stream_desc, PddlGenerator2 = pickle.load(f)
        PddlGenerator.copy(PddlGenerator2)
    if end_after <= 3:
        PddlGenerator.generate()
        return None

    # construct the actions
    if start_from <= 4:
        streams, predicates = stream_construction(
            llm_gpt, stream_desc, domain_task, init, feedback=feedback,
            shorten_message=shorten_message, max_attempts=max_step_4_attempts, max_iters=act_constr_iters,
            unsupported_keywords=None, generalize_predicate_types=generalize_predicates,
            feedback_level=act_constr_feedback_level,
        )
        PddlGenerator.generate()

        # Store the domain file separately
        domain_4_path = os.path.join(os.path.dirname(PddlGenerator.domain_file), "domain_4.pddl")
        with open(domain_4_path, 'w') as f:
            f.write(PddlGenerator.get_domain())
        """
        if checkpoints:
            with open(f"{Logger.directory}/checkpoint4.pkl", 'wb') as f:
                pickle.dump([types, type_hierarchy, predicates, actions, PddlGenerator], f)
        
    elif start_from == 5:
        with open(os.path.join(start_dir, "checkpoint4.pkl"), 'rb') as f:
            types, type_hierarchy, predicates, actions, PddlGenerator2 = pickle.load(f)
        PddlGenerator.copy(PddlGenerator2)
    if end_after <= 4:
        PddlGenerator.generate()
        return None"""

    # extract goal and initial state
    """
    if start_from <= 5:
        goal, state, objects = problem_extraction(llm_gpt, domain_task, type_hierarchy, predicates, shorten_message=shorten_message, max_attempts=max_step_5_attempts, feedback=feedback)
        PddlGenerator.generate()

        # Store the problem file separately
        problem_5_path = os.path.join(os.path.dirname(PddlGenerator.problem_file), "problem_5.pddl")
        with open(problem_5_path, 'w') as f:
            f.write(PddlGenerator.get_problem())
        
        if checkpoints:
            with open(f"{Logger.directory}/checkpoint5.pkl", 'wb') as f:
                pickle.dump([types, type_hierarchy, predicates, actions, objects, goal, state, PddlGenerator], f)
    elif start_from == 6:
        with open(os.path.join(start_dir, "checkpoint5.pkl"), 'rb') as f:
            types, type_hierarchy, predicates, actions, objects, goal, state, PddlGenerator2 = pickle.load(f)
        PddlGenerator.copy(PddlGenerator2)
    if end_after <= 5:
        PddlGenerator.generate()
        return None

    
    # Solve the generated PDDL
    PddlGenerator.generate() # Generate the final PDDL file
    plan = planning(llm_conn=llm_gpt, max_attempts=max_step_6_attempts, domain_desc=domain_task)

    plan_str = ("\t- " + "\n\t- ".join(plan)) if plan is not None else "No plan found."
    Logger.print("Plan:\n", plan_str)

    return plan"""
    return "ok"

if __name__ == "__main__":
    print("To demo the NL2Plan pipeline, instead run the main.py script in the root directory.")