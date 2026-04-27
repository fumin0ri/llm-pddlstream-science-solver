from collections import OrderedDict
import os, re, itertools, copy, signal
from typing import Literal

from .utils.pddl_output_utils import parse_new_predicates, parse_params, combine_blocks, remove_comments
from .utils.pddl_types import Predicate, Stream,Action
from .utils.paths import stream_construction_prompts as prompt_dir
from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.human_feedback import human_feedback
from .utils.pddl_errors import domain_errors
from .hierarchy_construction import Hierarchy
from .utils.llm_model import LLM_Chat, get_llm, shorten_messages

MESSAGE_HISTORY = {}
REVISION_HISTORY = None

@Logger.section("4 Stream Construction")
def stream_construction(
        llm_conn: LLM_Chat,
        stream_descs: dict[str, str],
        domain_desc_str: str,
        init,
        unsupported_keywords: list[str] | None = None,
        feedback: str | None = None,
        max_attempts: int = 8,
        shorten_message: bool = False,
        max_iters: int = 2,
        mirror_symmetry: bool = False,
        generalize_predicate_types: bool = False,
        feedback_level: Literal["domain", "stream", "both"] = "domain",
        revise_domain_iters: int = 0,
    ) -> tuple[list[Stream], list[Predicate]]:
    """
    Construct streams from a given domain description using an LLM_Chat language model.

    Args:
        llm_conn (LLM_Chat): The LLM_Chat language model connection.
        streams (dict[str, str]): A dictionary of streams to construct, where the keys are stream names and the values are stream descriptions.
        domain_desc_str (str): The domain description string.
        type_hierarchy (Hierarchy): The type hierarchy.
        unsupported_keywords (list[str]): A list of unsupported keywords.
        feedback (bool): Whether to request feedback from the language model. Defaults to True.
        max_attempts (int): The maximum number of messages to send to the language model. Defaults to 8.
        shorten_message (bool): Whether to shorten the messages sent to the language model. Defaults to False.
        max_iters (int): The maximum number of iterations to construct each stream. Defaults to 2.
        mirror_symmetry (bool): Whether to mirror any symmetrical predicates used process. Defaults to False.
        generalize_predicate_types (bool): Whether to allow generalization of predicate types after creation. Defaults to False.
        feedback_level (str): The level of feedback to request from the language model. Defaults to "domain".
        revise_domain_iters (int): The maximum number of iterations to revise the domain. Defaults to 4.

    Returns:
        list[Stream]: A list of constructed streams.
        list[Predicate]: A list of predicates.
    """
    global MESSAGE_HISTORY
    MESSAGE_HISTORY = {} # Reset the message history

    llm_conn.reset_token_usage()
    stream_feedback = feedback if (feedback_level == "stream" or feedback_level == "both") else None
    domain_feedback = feedback if (feedback_level == "domain" or feedback_level == "both") else None
    received_domain_feedback = None

    stream_list = "\n".join([f"- {name}: {desc}" for name, desc in stream_descs.items()])

    with open(os.path.join(prompt_dir, "main2.txt")) as f:
        act_constr_template = f.read().strip()
    act_constr_template = act_constr_template.replace('{domain_desc}', domain_desc_str)
    act_constr_template = act_constr_template.replace('{init_pddl}', init['signature'])
    act_constr_template = act_constr_template.replace('{init_code}', init['init'])
    act_constr_template = act_constr_template.replace('{stream_list}', stream_list)

    with open(os.path.join(prompt_dir, "feedback2.txt")) as f:
        feedback_template = f.read().strip()
    feedback_template = feedback_template.replace('{domain_desc}', domain_desc_str)
    feedback_template = feedback_template.replace('{init_pddl}', init['signature'])
    feedback_template = feedback_template.replace('{init_code}', init['init'])
    feedback_template = feedback_template.replace('{stream_list}', stream_list)

    predicates = []
    predicates.extend([init])
    predicates.extend([{'signature':"(done)"}])
    for iter in range(1):
        streams = []
        Logger.print(f"Starting iteration {iter + 1} of stream construction", subsection=False)
        ingoing_pred = copy.deepcopy(predicates)
        for stream_name, stream_desc in stream_descs.items():

            if received_domain_feedback is not None and received_domain_feedback.get(stream_name,None) is None:
                Logger.print("No feedback received for stream '", stream_name, "'. Retaining last version.", subsection=False)
                idx = [a["name"] for a in streams_before_feedback].index(stream_name)
                stream = streams_before_feedback[idx]
                streams.append(stream)
                continue

            stream, new_predicates = construct_stream(
                llm_conn, act_constr_template, feedback_template, stream_name, stream_desc, domain_desc_str, init, stream_descs, predicates,streams=streams,
                max_iters=max_attempts, feedback=stream_feedback, shorten_message=shorten_message, mirror_symmetry=mirror_symmetry,
                generalize_predicate_types=generalize_predicate_types, domain_feedback = received_domain_feedback, 
            )
            streams.append(stream)
            predicates.extend(new_predicates)

    
    Logger.print("Constructed streams:\n", "\n\n".join([
        str(stream) \
            .replace("'name':",             "\n\t'name':") \
            .replace("'parameters':",       "\n\t'parameters':") \
            .replace("'preconditions':",    "\n\t'preconditions':") \
            .replace("'effects':",          "\n\t'effects':") \
            .replace("}", "\n}")
        for stream in streams
    ]))
    setup_domain(streams, predicates,init)

    global REVISION_HISTORY # Reset the revision history
    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Stream_Construction_Tokens=(in_tokens, out_tokens))

    return streams, predicates

class LLMTimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise LLMTimeoutError("The function call timed out.")

def construct_stream(
        llm_conn: LLM_Chat,
        act_constr_prompt: str,
        feedback_template0: str,
        stream_name: str,
        stream_desc: str,
        domain_desc_str: str,
        init,
        stream_descs: dict[str, str],
        predicates: list[Predicate],
        streams:list[Stream],
        feedback_template: str = None,
        max_iters=8,
        shorten_message=False,
        feedback=True,
        mirror_symmetry=False,
        generalize_predicate_types=False,
        domain_feedback = None,
        type_hierarchy: Hierarchy = None,
        timeout_seconds: int = 600,
        max_retries: int = 3
    ) -> tuple[Stream, list[Predicate], dict[str, dict[int, str]]]:
    """
    Construct a stream from a given stream description using a LLM_Chat language model.

    Returns:
        Stream: The constructed stream.
        new predicates list[Predicate]: A list of new predicates.
    """
    global MESSAGE_HISTORY

    if max_iters < 1:
        raise ValueError("The maximum number of attempts during Stream Construction (step 4) must be at least 1.")

    act_constr_prompt = act_constr_prompt.replace('{stream_desc}', stream_desc)
    act_constr_prompt = act_constr_prompt.replace('{stream_name}', stream_name)
    feedback_template0 = feedback_template0.replace('{stream_desc}', stream_desc)
    feedback_template0 = feedback_template0.replace('{stream_name}', stream_name)
    if len(predicates) == 0:
        predicate_str = ""
    else:
        predicate_str = ""
        for i, pred in enumerate(predicates):
            predicate_str += f"{pred['signature']}\n"
    act_constr_prompt = act_constr_prompt.replace('{predicate_list}', predicate_str)
    feedback_template0 = feedback_template0.replace('{predicate_list}', predicate_str)

    if len(streams) == 0:
        streams_str = ""
    else:
        streams_str = ""
        for i, stre in enumerate(streams):
            streams_str += f"{stre['pddl']}\n\n"
    act_constr_prompt = act_constr_prompt.replace('{defined_streams}', streams_str)
    feedback_template0 = feedback_template0.replace('{defined_streams}', streams_str)

    messages = MESSAGE_HISTORY.get(stream_name, [{'role': 'user', 'content': act_constr_prompt}])

    received_feedback_at = None
    stream = None
    new_predicates: list[Predicate] = []
    last_error: Exception | None = None

    for iter in range(max_iters):
        Logger.print(f'Generating PDDL of stream: `{stream_name}` | # of messages: {len(messages)}', subsection=False)

        if iter > 0:
            messages.append({
                'role': 'user',
                'content': (
                    "Parsing failed on previous output. Please match each heading exactly with the example."
                )
            })


        msgs_to_send = messages

        llm_output = None
        retries = 0
        while retries < max_retries:
            try:
                # Set the signal handler and alarm
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout_seconds)

                # This is the line that might hang
                llm_output = llm_conn.get_response(prompt=None, messages=msgs_to_send)

                # If successful, cancel the alarm and break the retry loop
                signal.alarm(0)
                break
            except LLMTimeoutError:
                signal.alarm(0)  # Cancel the alarm
                retries += 1
                Logger.print(
                    f"LLM call for stream '{stream_name}' timed out. Retrying ({retries}/{max_retries})...",
                    subsection=False
                )

        if llm_output is None:
            last_error = LLMTimeoutError(
                f"LLM did not respond for stream '{stream_name}' after {max_retries} retries."
            )
            # Try the next outer iteration if available
            continue

        messages.append({'role': 'assistant', 'content': llm_output})

        try:
            llm_output = clean_llm_output(llm_output)
            new_predicates = parse_predicates(llm_output)

            # Parse the stream first to validate syntax/structure
            stream = parse_stream(llm_output, stream_name, stream_desc)

            # Success → exit the construction loop
            break

        except Exception as e:
            Logger.print(f"Error while parsing stream '{stream_name}': {e}", subsection=False)
            last_error = e
            # Go to next iteration (re-prompt/retry)
            continue


    for i in range(max_iters):
        
        feedback_prompt = feedback_template0
        feedback_prompt = feedback_prompt.replace('{stream_pddl}', stream['pddl'])
        if len(new_predicates) == 0:
            new_predicate_str = ""
        else:
            new_predicate_str = new_predicates[0]['signature']
        feedback_prompt = feedback_prompt.replace('{new_predicates}', new_predicate_str)
        feedback_prompt = feedback_prompt.replace('{stream_code}', stream['code'])

        for iter in range(max_iters):
            feedback_msg = get_llm_feedback(llm_conn, feedback_prompt,stream_name)
            if feedback_msg is not None:
                messages = [
                    {'role': 'user', 'content': act_constr_prompt},
                    {'role': 'assistant', 'content': llm_output},
                    {'role': 'user', 'content': feedback_msg}
                ]
                try:
                    llm_response = llm_conn.get_response(messages=messages)
                    llm_output = clean_llm_output(llm_response)
                    new_predicates = parse_predicates(llm_output)

                            # Parse the stream first to validate syntax/structure
                    stream = parse_stream(llm_output, stream_name, stream_desc)

                            # Success → exit the construction loop
                    break

                except Exception as e:
                    Logger.print(f"Error while parsing stream '{stream_name}': {e}", subsection=False)
                    last_error = e
                            # Go to next iteration (re-prompt/retry)
                    continue
            else:
                break

        if feedback_msg is not None:
            continue
        else:
            break

    # Save the message history for this stream in case we need to revise it
    MESSAGE_HISTORY[stream_name] = messages

    if stream is None:
        # Ensure we don't return unbound variables and provide a helpful error
        raise RuntimeError(
            f"construct_stream failed for '{stream_name}' after {max_iters} iterations; last error: {last_error}"
        )

    return stream, new_predicates



def setup_domain(streams: list[Stream], predicates: list[Predicate],init:Predicate):
    PddlGenerator.reset_streams()
    PddlGenerator.set_init(init)
    for stream in streams:
        PddlGenerator.add_stream(stream)
    predicate_str = ""
    for i, pred in enumerate(predicates):
        predicate_str += f"{pred['signature']}\n"
    PddlGenerator.set_predicates(predicate_str)
    predicate_str = predicate_str.replace("\n", "\n\n") # Add extra newline for better readability
    domain, *_ = PddlGenerator.generate()
    return domain

def parse_stream(llm_output: str, stream_name: str, stream_desc: str) -> Stream:
    """
    Parse an stream from a given LLM output.

    Args:
        llm_output (str): The LLM output.
        stream_name (str): The name of the stream.

    Returns:
        Stream: The parsed stream.
    """
    try:
        stream_pddl = llm_output.split("Stream pddl\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Stream pddl' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    try:
        stream_code = llm_output.split("Stream code\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except:
        raise Exception("Could not find the 'Stream code' section in the output. Provide the entire response, including all headings even if some are unchanged.")
    return {"name": stream_name, "pddl": stream_pddl, "code": stream_code, "desc": stream_desc}

def parse_predicates(llm_output: str) -> list[Predicate] | None:
    try:
        # 「New Predicates\n」以降を取り出し、##（次のセクション）があればそこで区切る
        section = llm_output.split("New Predicates\n")[1].split("##")[0]

        # ``` で囲まれた部分を抽出
        predicate = section.split("```")[-2].strip(" `\n")
    except Exception:
        raise Exception(
            "Could not find the 'Stream pddl' section in the output. "
            "Provide the entire response, including all headings even if some are unchanged."
        )

    if not predicate:
        return []

    # 通常のパース結果を返す
    return [{"signature": predicate}]


def prune_predicates(predicates: list[Predicate], streams: list[Stream]) -> list[Predicate]:
    """
    Remove predicates that are not used in any stream.

    Args:
        predicates (list[Predicate]): A list of predicates.
        streams (list[Stream]): A list of streams.

    Returns:
        list[Predicate]: The pruned list of predicates.
    """
    used_predicates = []
    for pred in predicates:
        for stream in streams:
            # Add a space or a ")" to avoid partial matches
            names = [f"({pred['name']} ", f"({pred['name']})", f"( {pred['name']} "]
            for name in names:
                if name in stream['pddl']:
                    used_predicates.append(pred)
                    Logger.log(f"Predicate '{pred['name']}' is used in stream '{stream['name']}'", subsection=False)
                    break
            else: # If the predicate is not used in this stream, check the next stream
                continue
            break # If the predicate is used in this stream, skip checking the rest of the streams
    return used_predicates


def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```").replace("```text","```")
    llm_output = llm_output.replace("```python", "```")
    llm_output = llm_output.replace("```lisp", "```")
    return llm_output


def get_llm_feedback(llm_conn: LLM_Chat, feedback_prompt: str,stream_name: str):
    max_retries = 3
    timeout_seconds = 600
    retries = 0
    while retries < max_retries:
        try:
                # Set the signal handler and alarm
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)

                # This is the line that might hang
            feedback_output = llm_conn.get_response(feedback_prompt)

                # If successful, cancel the alarm and break the retry loop
            signal.alarm(0)
            break
        except LLMTimeoutError:
            signal.alarm(0)  # Cancel the alarm
            retries += 1
            Logger.print(
                f"LLM call for stream '{stream_name}' timed out. Retrying ({retries}/{max_retries})...",
                subsection=False
            )
    if "no feedback" in feedback_output.lower() or len(feedback_output.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback_output)
        return None
    else:
        if feedback_output.count("```") >= 2:
            feedback_output = combine_blocks(feedback_output)
        Logger.print("FEEDBACK:\n", feedback_output)
        feedback = "## Feedback\nYou received the following feedback. Address this feedback. Note that you cannot refer to the above solution. " + feedback_output + "\n\n The contents of the feedback take precedence over the contents of ## Stream. Please modify your response and ensure it matches the format of the ## Example exactly. ## Reply only to the stream specified in the stream, and do not include any other streams in your reply. Please include all headings ## Stream pddl, ## New Predicates, and ## Stream code in your response."
        return feedback