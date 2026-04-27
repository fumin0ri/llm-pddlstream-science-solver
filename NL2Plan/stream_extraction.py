import os

from .utils.paths import stream_extraction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.human_feedback import human_feedback
from .hierarchy_construction import Hierarchy
from .utils.llm_model import LLM_Chat, get_llm

@Logger.section("3 Stream Extraction")
def stream_extraction(llm_conn: LLM_Chat, domain_desc_str: str, init, feedback: str | None = None) -> dict[str, str]:
    """
    Extracts streams from a given domain description using a GPT_Chat language model.

    Args:
        llm_conn (LLM_Chat): The language model.
        domain_desc_str (str): The domain description string.
        type_hierarchy (Hierarchy): The type hierarchy.

    Returns:
        dict[str, str]: A dictionary of extracted streams, where the keys are action names and the values are action descriptions.
    """
    llm_conn.reset_token_usage()

    with open(os.path.join(prompt_dir, "feedback2.txt")) as f:
        feedback_template = f.read().strip()
    feedback_template = feedback_template.replace('{domain_desc}', domain_desc_str)
    feedback_template = feedback_template.replace('{init_pddl}', init['signature'])
    feedback_template = feedback_template.replace('{init_code}', init['init'])

    with open(os.path.join(prompt_dir, "solution.txt")) as f:
        solution_template = f.read().strip()
    solution_template = solution_template.replace('{domain_desc}', domain_desc_str)


    with open(os.path.join(prompt_dir, "main2.txt")) as f:
        calculation_template = f.read().strip()
    calculation_prompt = calculation_template.replace('{domain_desc}', domain_desc_str)
    calculation_prompt = calculation_prompt.replace('{init_pddl}', init['signature'])
    calculation_prompt = calculation_prompt.replace('{init_code}', init['init'])

    solution =llm_conn.get_response(prompt=solution_template)
    calculation_prompt = calculation_prompt.replace('{solution}', solution)
    feedback_template = feedback_template.replace('{solution}', solution)


    llm_output = llm_conn.get_response(prompt=calculation_prompt)
    llm_output = clean_llm_output(llm_output)

    streams = parse_streams(llm_output)

    if feedback is not None:
        if feedback.lower() == "human":
            stream_strs = "\n".join([f"- {name}: {desc}" for name, desc in streams.items()])
            feedback_msg = human_feedback(f"\n\nThe streams extracted are:\n{stream_strs}\n")
        else:
            feedback_msg = get_llm_feedback(llm_conn, streams, feedback_template)
        if feedback_msg is not None:
            messages = [
                {'role': 'user', 'content': calculation_prompt},
                {'role': 'assistant', 'content': llm_output},
                {'role': 'user', 'content': feedback_msg}
            ]
            llm_response = llm_conn.get_response(messages=messages)
            llm_response = clean_llm_output(llm_response)
            streams = parse_streams(llm_response)

    # Log results
    stream_strs = [f"{name}:\n{desc}" for name, desc in streams.items()]
    Logger.print(f"Extracted {len(streams)} streams:\n\n - ", "\n\n - ".join(stream_strs))

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Action_Extraction_Tokens=(in_tokens, out_tokens))

    return streams

def parse_streams(llm_output: str) -> dict[str, str]:
    """
    Parses the output of the action extraction prompt to extract the action names and descriptions.

    Args:
        llm_output (str): The output of the action extraction prompt.

    Returns:
        dict[str, str]: A dictionary of extracted streams, where the keys are action names and the values are action descriptions.
    """

    splits = llm_output.replace("markdown","").split("```")
    action_outputs = [splits[i].strip() for i in range(1, len(splits), 2)] # Every other split *should* be an action 

    streams = {}
    for action in action_outputs:
        name = action.split("\n")[0].strip()
        desc = action.split("\n", maxsplit=1)[1].strip() # Works even if there is no blank line
        streams[name] = desc

    return streams

def get_llm_feedback(llm_conn: LLM_Chat, streams: dict[str, str], feedback_template: str) -> str | None:
    """
    Gets feedback on the extracted streams.

    Args:
        llm_conn (LLM_Chat): The LLM_Chat language model connection.
        streams (dict[str, str]): A dictionary of extracted streams, where the keys are action names and the values are action descriptions.
        feedback_template (str): The feedback template to use.

    Returns:
        str | None: The feedback on the extracted streams.
    """
    action_str = "\n".join([f"- {name}: {desc}" for name, desc in streams.items()])
    feedback_prompt = feedback_template.replace('{streams}', action_str)

    feedback = llm_conn.get_response(prompt=feedback_prompt)

    if "no feedback" in feedback.lower() or len(feedback.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback)
        return None

    if feedback.count("```") == 2:
        feedback = feedback.split("```")[1].strip()

    Logger.print("FEEDBACK:\n", feedback)
    feedback = "## Feedback\n" + feedback + "\nStart with a \"## Response\" header, then go through all the streams, even those kept from before, under a \"## streams\" header as before. You need to keep the previous formatting, outputting each action within independent (\"```\") with the first line as the name, the second line empty, and the third line as the description. Answers must strictly adhere to the format provided as an example."
    feedback += "\n\n## Response\n"
    return feedback

def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```").replace("```lisp","```")
    return llm_output