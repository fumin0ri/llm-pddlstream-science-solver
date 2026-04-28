import copy
import os
import signal
from typing import Literal

from .utils.pddl_output_utils import combine_blocks
from .utils.pddl_types import Predicate, Stream
from .utils.paths import stream_construction_prompt_dir as prompt_dir
from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.llm_model import LLM_Chat

MESSAGE_HISTORY = {}


@Logger.section("4 Stream Construction")
def build_streams(
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
        feedback_level: Literal["domain", "stream", "both"] = "stream",
    ) -> tuple[list[Stream], list[Predicate]]:
    global MESSAGE_HISTORY
    MESSAGE_HISTORY = {}

    llm_conn.reset_token_usage()
    if feedback not in (None, "llm"):
        raise ValueError(f"Unsupported feedback mode: {feedback}")

    if feedback_level == "domain":
        Logger.print(
            "Domain-level feedback is not implemented in build_streams yet; "
            "falling back to per-stream feedback.",
            subsection=False
        )
        stream_feedback = feedback
    else:
        stream_feedback = feedback if feedback_level in {"stream", "both"} else None

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

    predicates = [init, {'signature': "(done)"}]
    streams = []
    Logger.print("Starting stream construction", subsection=False)

    for stream_name, stream_desc in stream_descs.items():
        stream, new_predicates = construct_stream(
            llm_conn,
            act_constr_template,
            feedback_template,
            stream_name,
            stream_desc,
            domain_desc_str,
            init,
            stream_descs,
            predicates,
            streams=streams,
            parse_attempts=max_attempts,
            feedback_rounds=max_iters,
            feedback=stream_feedback,
            shorten_message=shorten_message,
            mirror_symmetry=mirror_symmetry,
            generalize_predicate_types=generalize_predicate_types,
        )
        streams.append(stream)
        predicates.extend(new_predicates)

    Logger.print("Constructed streams:\n", "\n\n".join([
        str(stream)
            .replace("'name':", "\n\t'name':")
            .replace("'parameters':", "\n\t'parameters':")
            .replace("'preconditions':", "\n\t'preconditions':")
            .replace("'effects':", "\n\t'effects':")
            .replace("}", "\n}")
        for stream in streams
    ]))
    setup_domain(streams, predicates, init)

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
        streams: list[Stream],
        feedback_template: str = None,
        parse_attempts: int = 8,
        feedback_rounds: int = 2,
        shorten_message: bool = False,
        feedback: str | None = True,
        mirror_symmetry: bool = False,
        generalize_predicate_types: bool = False,
        timeout_seconds: int = 600,
        max_retries: int = 3
    ) -> tuple[Stream, list[Predicate]]:
    global MESSAGE_HISTORY

    if parse_attempts < 1:
        raise ValueError("The maximum number of attempts during Stream Construction must be at least 1.")
    if feedback_rounds < 1:
        raise ValueError("The number of feedback rounds during Stream Construction must be at least 1.")

    act_constr_prompt = act_constr_prompt.replace('{stream_desc}', stream_desc)
    act_constr_prompt = act_constr_prompt.replace('{stream_name}', stream_name)
    feedback_template0 = feedback_template0.replace('{stream_desc}', stream_desc)
    feedback_template0 = feedback_template0.replace('{stream_name}', stream_name)

    predicate_str = "".join(f"{pred['signature']}\n" for pred in predicates)
    act_constr_prompt = act_constr_prompt.replace('{predicate_list}', predicate_str)
    feedback_template0 = feedback_template0.replace('{predicate_list}', predicate_str)

    streams_str = "".join(f"{stre['pddl']}\n\n" for stre in streams)
    act_constr_prompt = act_constr_prompt.replace('{defined_streams}', streams_str)
    feedback_template0 = feedback_template0.replace('{defined_streams}', streams_str)

    messages = MESSAGE_HISTORY.get(stream_name, [{'role': 'user', 'content': act_constr_prompt}])
    stream = None
    new_predicates: list[Predicate] = []
    last_error: Exception | None = None

    for iteration in range(parse_attempts):
        Logger.print(f'Generating PDDL of stream: `{stream_name}` | # of messages: {len(messages)}', subsection=False)
        if iteration > 0:
            messages.append({
                'role': 'user',
                'content': "Parsing failed on previous output. Please match each heading exactly with the example."
            })

        llm_output = None
        retries = 0
        while retries < max_retries:
            try:
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout_seconds)
                llm_output = llm_conn.get_response(prompt=None, messages=messages)
                signal.alarm(0)
                break
            except LLMTimeoutError:
                signal.alarm(0)
                retries += 1
                Logger.print(
                    f"LLM call for stream '{stream_name}' timed out. Retrying ({retries}/{max_retries})...",
                    subsection=False
                )

        if llm_output is None:
            last_error = LLMTimeoutError(
                f"LLM did not respond for stream '{stream_name}' after {max_retries} retries."
            )
            continue

        try:
            llm_output = clean_llm_output(llm_output)
            new_predicates = parse_predicates(llm_output)
            stream = parse_stream(llm_output, stream_name, stream_desc)
            messages.append({'role': 'assistant', 'content': llm_output})
            break
        except Exception as exc:
            Logger.print(f"Error while parsing stream '{stream_name}': {exc}", subsection=False)
            last_error = exc
            continue

    if stream is None:
        raise RuntimeError(
            f"construct_stream failed for '{stream_name}' after {parse_attempts} iterations; last error: {last_error}"
        )

    if feedback is not None:
        for _ in range(feedback_rounds):
            feedback_prompt = feedback_template0
            feedback_prompt = feedback_prompt.replace('{stream_pddl}', stream['pddl'])
            new_predicate_str = new_predicates[0]['signature'] if new_predicates else ""
            feedback_prompt = feedback_prompt.replace('{new_predicates}', new_predicate_str)
            feedback_prompt = feedback_prompt.replace('{stream_code}', stream['code'])

            feedback_msg = get_llm_feedback(llm_conn, feedback_prompt, stream_name)
            if feedback_msg is None:
                break

            messages = [
                {'role': 'user', 'content': act_constr_prompt},
                {'role': 'assistant', 'content': llm_output},
                {'role': 'user', 'content': feedback_msg}
            ]
            try:
                llm_response = llm_conn.get_response(messages=messages)
                llm_output = clean_llm_output(llm_response)
                new_predicates = parse_predicates(llm_output)
                stream = parse_stream(llm_output, stream_name, stream_desc)
            except Exception as exc:
                Logger.print(f"Error while parsing stream '{stream_name}': {exc}", subsection=False)
                last_error = exc
                continue
            messages = [
                {'role': 'user', 'content': act_constr_prompt},
                {'role': 'assistant', 'content': llm_output},
            ]

    MESSAGE_HISTORY[stream_name] = messages
    return stream, new_predicates


def setup_domain(streams: list[Stream], predicates: list[Predicate], init: Predicate):
    PddlGenerator.reset_streams()
    PddlGenerator.set_init(init)
    for stream in streams:
        PddlGenerator.add_stream(stream)
    predicate_str = "".join(f"{pred['signature']}\n" for pred in predicates)
    PddlGenerator.set_predicates(predicate_str)
    domain, *_ = PddlGenerator.generate()
    return domain


def parse_stream(llm_output: str, stream_name: str, stream_desc: str) -> Stream:
    try:
        stream_pddl = llm_output.split("Stream pddl\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except Exception:
        raise Exception(
            "Could not find the 'Stream pddl' section in the output. "
            "Provide the entire response, including all headings even if some are unchanged."
        )
    try:
        stream_code = llm_output.split("Stream code\n")[1].split("##")[0].split("```")[-2].strip(" `\n")
    except Exception:
        raise Exception(
            "Could not find the 'Stream code' section in the output. "
            "Provide the entire response, including all headings even if some are unchanged."
        )
    return {"name": stream_name, "pddl": stream_pddl, "code": stream_code, "desc": stream_desc}


def parse_predicates(llm_output: str) -> list[Predicate]:
    try:
        section = llm_output.split("New Predicates\n")[1].split("##")[0]
        predicate = section.split("```")[-2].strip(" `\n")
    except Exception:
        raise Exception(
            "Could not find the 'New Predicates' section in the output. "
            "Provide the entire response, including all headings even if some are unchanged."
        )

    if not predicate:
        return []
    return [{"signature": predicate}]


def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```").replace("```text", "```")
    llm_output = llm_output.replace("```python", "```").replace("```lisp", "```")
    return llm_output


def get_llm_feedback(llm_conn: LLM_Chat, feedback_prompt: str, stream_name: str):
    max_retries = 3
    timeout_seconds = 600
    retries = 0
    feedback_output = None

    while retries < max_retries:
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(timeout_seconds)
            feedback_output = llm_conn.get_response(feedback_prompt)
            signal.alarm(0)
            break
        except LLMTimeoutError:
            signal.alarm(0)
            retries += 1
            Logger.print(
                f"LLM call for stream '{stream_name}' timed out. Retrying ({retries}/{max_retries})...",
                subsection=False
            )

    if feedback_output is None:
        raise LLMTimeoutError(
            f"Feedback generation for stream '{stream_name}' timed out after {max_retries} retries."
        )

    if "no feedback" in feedback_output.lower() or len(feedback_output.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        Logger.log(feedback_output)
        return None

    if feedback_output.count("```") >= 2:
        feedback_output = combine_blocks(feedback_output)
    Logger.print("FEEDBACK:\n", feedback_output)
    return (
        "## Feedback\nYou received the following feedback. Address this feedback. "
        "Note that you cannot refer to the above solution. "
        + feedback_output
        + "\n\nThe contents of the feedback take precedence over the contents of ## Stream. "
          "Please modify your response and ensure it matches the format of the ## Example exactly. "
          "Reply only to the stream specified in the prompt, and include all headings "
          "## Stream pddl, ## New Predicates, and ## Stream code in your response."
    )
