import os

from .utils.pddl_output_utils import combine_blocks
from .utils.paths import initial_facts_extraction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.human_feedback import human_feedback
from .utils.llm_model import LLM_Chat, get_llm
from .utils.pddl_types import Predicate
from .utils.pddl_generator import PddlGenerator

@Logger.section("1 Init Facts Extraction")
def initial_facts_extraction(llm_conn: LLM_Chat, domain_desc_str: str, feedback: str | None = None):
    llm_conn.reset_token_usage()

    with open(os.path.join(prompt_dir, "main2.txt")) as f:
        type_extr_template = f.read().strip()
    type_extr_prompt = type_extr_template.replace('{domain_desc}', domain_desc_str)
    Logger.log("PROMPT:\n", type_extr_prompt)

   
    for iter in range(8):
        try:
            llm_output = llm_conn.get_response(type_extr_prompt)
            llm_output = clean_llm_output(llm_output)

            Init = parse_init(llm_output)
                # Success → exit the construction loop
            break

        except Exception as e:
            last_error = e
            # Go to next iteration (re-prompt/retry)
            continue
    
    
    with open(os.path.join(prompt_dir, "feedback2.txt")) as f:
        feedback_template = f.read().strip()
    feedback_prompt = feedback_template.replace('{domain_desc}', domain_desc_str)
    feedback_prompt = feedback_prompt.replace('{init_pddl}', Init['signature'])
    feedback_prompt = feedback_prompt.replace('{init_code}', Init['init'])
    feedback_prompt = feedback_prompt.replace('{init_ana}', Init['raw'])


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
            llm_response = clean_llm_output(llm_response)
            Init = parse_init(llm_response)
    
    # Log results
    PddlGenerator.set_init(Init)
    Logger.print(f"Extracted",Init)

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Type_Extraction_Tokens=(in_tokens, out_tokens))

    return Init


def parse_init(llm_output: str)-> Predicate:
    try:
        init_pddl = llm_output.split("Predicates\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Predicate' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    try:
        init_code = llm_output.split("Initial Facts\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Initial Facts' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    try:
        ana = llm_output.split("Problem analysis\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Problem analysis' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    
    return {"raw": ana,"signature": init_pddl, "init": init_code}

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
        feedback = "## Feedback\nYou received the following feedback. Address this feedback. Note that you cannot refer to the above solution. " + feedback_output + "\n\nPlease modify your response and ensure it matches the format of the ## Example exactly."
        return feedback

def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```").replace("```lisp","```")
    return llm_output