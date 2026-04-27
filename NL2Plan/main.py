import os, pickle
from typing import Literal

from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator

from .utils.llm_model import get_llm
from .initial_facts_extraction import initial_facts_extraction
from .stream_extraction import stream_extraction
from .stream_construction import stream_construction


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
        init = initial_facts_extraction(llm_gpt, domain_task, feedback=feedback)
        PddlGenerator.generate()


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
    return "ok"

if __name__ == "__main__":
    print("To demo the NL2Plan pipeline, instead run the main.py script in the root directory.")