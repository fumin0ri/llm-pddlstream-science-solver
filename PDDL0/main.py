import os, datetime, sys
from io import StringIO

from .paths import results_dir, prompt_dir
from NL2Plan.utils.llm_model import get_llm, shorten_messages
from NL2Plan.utils.pddl_errors import domain_errors, problem_errors
from NL2Plan.utils.planner import run_planner
from NL2Plan.planning import parse_and_update

def main(domain: str, domain_task_desc: str, llm: str = "gpt-4o", instance_name: str = None, max_attempts: int = 5, validation_enabled: bool = True, shorten_message: bool = True):
    dt = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    if instance_name is None:
        instance_name = dt
    out_dir = os.path.join(results_dir, domain, instance_name)
    os.makedirs(out_dir, exist_ok=True)
    domain_file = os.path.join(out_dir, "domain.pddl")
    problem_file = os.path.join(out_dir, "problem.pddl")
    plan_file = os.path.join(out_dir, "plan")
    log_file = os.path.join(out_dir, "planner_log.txt")

    with open(os.path.join(prompt_dir, "prompt.txt"), "r") as file:
        prompt = file.read()
    prompt = prompt.replace("{domain_task_desc}", domain_task_desc)
    messages = [
        {'role': 'user', 'content': prompt}
    ]

    # Load the LLM
    llm = get_llm(llm)
    llm.reset_token_usage()

    # Capture all prints

    with Capturing() as output:
        # Try to generate a domain and problem
        domain, problem = None, None
        while max_attempts > 0:
            output.ping(f"Starting attempt with {max_attempts} attempts left.\n")

            max_attempts -= 1
            errors = []

            # Save the messages
            save_messages(messages, out_dir)

            if shorten_message:
                to_send = shorten_messages(messages)
            else:
                to_send = messages
            attempt = llm.get_response(messages=to_send)
            messages.append({'role': 'assistant', 'content': attempt})

            output.ping("Response received.\n")

            try:
                new_domain, new_problem = parse_and_update(attempt, overwrite=False)
                if new_domain is not None:
                    domain = new_domain
                if new_problem is not None:
                    problem = new_problem
            except Exception as e:
                errors.append(str(e))

            output.ping(f"\tParsed. Domain: {domain is not None}, Problem: {problem is not None}, Errors: {len(errors)}\n")

            if domain is not None and validation_enabled:
                with open(domain_file, "w") as file:
                    file.write(domain)
                validation_errors = domain_errors(domain_file)
                print(f"Domain errors: {validation_errors}")
                if validation_errors:
                    errors.append(validation_errors)

            output.ping(f"\tValidated domain. Errors: {len(errors)}\n")

            if problem is not None and domain is not None and validation_enabled:
                with open(problem_file, "w") as file:
                    file.write(problem)
                validation_errors = problem_errors(problem_file, domain_file)
                print(f"Problem errors: {validation_errors}")
                if validation_errors:
                    errors.append(validation_errors)

            output.ping(f"\tValidated problem. Errors: {len(errors)}\n")

            if not errors:
                output.ping(f"\tNo errors found. Exiting.\n")
                break

            output.ping(f"\tErrors found. Retrying.\n")
            with open(os.path.join(prompt_dir, "error.txt"), "r") as file:
                prompt = file.read()
            prompt = prompt.replace("{errors}", "\n\n".join(errors))
            if domain is not None:
                prompt = prompt.replace("{domain}", domain)
            else:
                prompt = prompt.replace("{domain}", "No domain has been possible to parse yet.")
            if problem is not None:
                prompt = prompt.replace("{problem}", problem)
            else:
                prompt = prompt.replace("{problem}", "No problem has been possible to parse yet.")
            messages.append({'role': 'user', 'content': prompt})

        # Try to find a plan
        if domain is not None and problem is not None:
            output.ping("Finding a plan.\n")
            with open(domain_file, "w") as file:
                file.write(domain)
            with open(problem_file, "w") as file:
                file.write(problem)
            cost, plan = run_planner(domain_file, problem_file, plan_file, log_file)
            messages.append({
                'role': 'meta',
                'content': f"Plan cost: {cost}\nPlan:\n{plan}"
            })
            print(f"Plan cost: {cost}\nPlan:\n{plan}")
        else:
            output.ping("No plan was found because domain or problem could not be generated.\n")
            messages.append({
                'role': 'meta',
                'content': "No plan was found because domain or problem could not be generated."
            })
            plan = None
            print("No plan was found because domain or problem could not be generated.")

    # Save the messages
    save_messages(messages, out_dir)
    output.ping("Messages saved.\n")

    # Save the token usage
    in_tokens, out_tokens = llm.token_usage()
    with open(os.path.join(out_dir, "meta.txt"), "w") as file:
        file.write(f"Input tokens: {in_tokens}\n")
        file.write(f"Output tokens: {out_tokens}\n")
        file.write(f"Ran at: {dt}\n")
        file.write(f"Terminal call: python {' '.join(sys.argv)}\n")
    with open(os.path.join(out_dir, "prints.log"), "w") as file:
        file.write("\n".join(output))

    return plan

def save_messages(messages, out_dir):
    with open(os.path.join(out_dir, "messages.txt"), "w") as file:
        for message in messages:
            file.write(f"{'-'*35} {message['role']} {'-'*35}\n{message['content']}\n{'-'*80}\n")

class Capturing(list):
    # From https://stackoverflow.com/a/16571630/118173
    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = self._stringio = StringIO()
        return self
    def __exit__(self, *args):
        self.extend(self._stringio.getvalue().splitlines())
        del self._stringio    # free up some memory
        sys.stdout = self._stdout
    def ping(self, text):
        dt = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._stdout.write(f"{dt}: {text}")
        self._stdout.flush()