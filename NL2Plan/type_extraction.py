import os

from .utils.pddl_output_utils import combine_blocks
from .utils.paths import type_extraction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.human_feedback import human_feedback
from .utils.llm_model import LLM_Chat, get_llm

@Logger.section("1 Type Extraction")
def type_extraction(llm_conn: LLM_Chat, domain_desc_str: str, feedback: str | None = None):
    llm_conn.reset_token_usage()

    with open(os.path.join(prompt_dir, "main.txt")) as f:
        type_extr_template = f.read().strip()
    type_extr_prompt = type_extr_template.replace('{domain_desc}', domain_desc_str)
    Logger.log("PROMPT:\n", type_extr_prompt)

    llm_output = llm_conn.get_response(type_extr_prompt)

    types = parse_types(llm_output)
    type_str = "\n".join([f"- {v}" for v in types.values()])

    with open(os.path.join(prompt_dir, "feedback.txt")) as f:
        feedback_template = f.read().strip()
    feedback_prompt = feedback_template.replace('{domain_desc}', domain_desc_str)
    feedback_prompt = feedback_prompt.replace('{type_list}', type_str)

    if feedback is not None:
        if feedback.lower() == "human":
            feedback_msg = human_feedback(f"\n\nThe types extracted are:\n{type_str}\n")
        else:
            feedback_msg = get_llm_feedback(llm_conn, feedback_prompt)
        if feedback_msg is not None:
            messages = [
                {'role': 'user', 'content': type_extr_prompt},
                {'role': 'assistant', 'content': llm_output},
                {'role': 'user', 'content': feedback_msg}
            ]
            llm_response = llm_conn.get_response(messages=messages)
            types = parse_types(llm_response)
            type_str = "\n".join([f"- {v}" for v in types.values()])

    # Log results
    Logger.print(f"Extracted {len(types)} types:\n", type_str)

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Type_Extraction_Tokens=(in_tokens, out_tokens))

    return [v for v in types.values()]

def parse_types(llm_output: str):
    if "## Types" in llm_output:
        header = llm_output.split("## Types")[1].split("\n## ")[0]
    else:
        header = llm_output
    dot_list = combine_blocks(header)
    if len(dot_list) == 0:
        dot_list = "\n".join([l for l in header.split("\n") if l.strip().startswith("-")])
    if dot_list.count("-") == 0: # No types
        return {}
    types = dot_list.split('\n')
    types = [t.strip("- \n*") for t in types if t.strip("- \n*")] # Remove empty strings and dashes
    type_dict = {}
    for type in types:
        name, desc = type.split(":",1) if ":" in type else (type, "")
        name = name.strip(" *:").replace(" ", "_")
        desc = name + ": " + desc.strip()
        if name not in type_dict:
            type_dict[name] = desc
        elif len(type_dict[name]) < len(desc):
            type_dict[name] = desc
    return type_dict

def get_llm_feedback(llm_conn: LLM_Chat, feedback_prompt: str):
    feedback_output = llm_conn.get_response(feedback_prompt)
    if "no feedback" in feedback_output.lower() or len(feedback_output.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback_output)
        return None
    else:
        if feedback_output.count("```") >= 2:
            feedback_output = combine_blocks(feedback_output)
        Logger.print("FEEDBACK:\n", feedback_output)
        feedback = "## Feedback\nYou received the following feedback on the above final type selection. Address this feedback and respond with a corrected type list within a new markdown code block. Note that you cannot refer to the above solution. " + feedback_output + "\nHowever, you shouldn't create any new types that haven't been checked above unless instructed to do so."
        return feedback