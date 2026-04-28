import os
from typing import Literal

from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.llm_model import get_llm
from .extract_initial_facts import extract_initial_facts
from .extract_streams import extract_streams
from .build_streams import build_streams


def run_pipeline(
        domain_name: str,
        domain_task: str,
        engine: str,
        act_constr_iters: int = 2,
        act_constr_feedback_level: Literal["domain", "stream", "both"] = "stream",
        max_step_4_attempts: int = 5,
        feedback: str | None = None,
        instance_name: str = None,
        shorten_message: bool = True,
        generalize_predicates: bool = True,
    ) -> str:
    Logger.start(
        domain_name,
        domain_desc_task=domain_task,
        engine=engine,
        act_constr_iters=act_constr_iters,
        act_constr_feedback_level=act_constr_feedback_level,
        max_step_4_attempts=max_step_4_attempts,
        feedback=feedback,
        instance_name=instance_name,
        shorten_message=shorten_message,
        generalize_predicates=generalize_predicates,
    )
    if max_step_4_attempts < 1:
        raise ValueError("The maximum number of attempts during Stream Construction must be at least 1.")

    PddlGenerator.start()
    llm_gpt = get_llm(engine=engine)
    Logger.add_domain_desc(domain_task)

    init = extract_initial_facts(llm_gpt, domain_task, feedback=feedback)
    PddlGenerator.generate()

    stream_desc = extract_streams(llm_gpt, domain_task, init, feedback=feedback)
    PddlGenerator.generate()

    build_streams(
        llm_gpt,
        stream_desc,
        domain_task,
        init,
        feedback=feedback,
        shorten_message=shorten_message,
        max_attempts=max_step_4_attempts,
        max_iters=act_constr_iters,
        unsupported_keywords=None,
        generalize_predicate_types=generalize_predicates,
        feedback_level=act_constr_feedback_level,
    )
    PddlGenerator.generate()

    domain_4_path = os.path.join(os.path.dirname(PddlGenerator.domain_file), "domain_4.pddl")
    with open(domain_4_path, 'w') as f:
        f.write(PddlGenerator.get_domain())
    return "ok"


if __name__ == "__main__":
    print("To run the pipeline, execute the root main.py script.")
