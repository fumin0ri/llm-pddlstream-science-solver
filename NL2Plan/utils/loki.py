import os, subprocess

from .logger import Logger
from .paths import loki_dir

def domain_errors(domain_file: str) -> str | None:
    """Check for domain errors."""

    if not os.path.exists(f"{loki_dir}/domain"):
        Logger.print(f"Could not find the Loki domain at '{loki_dir}/domain'")
        return None

    try:
        subprocess.check_output([f"{loki_dir}/domain", domain_file], stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as exc:
        errors = exc.output.decode().strip()
        print(errors)
        if "<Signals.SIGABRT: 6>" in errors:
            Logger.print("Loki could not find the domain or problem file.")
            return None
        lines = errors.split("\n")
        if len(lines) < 3:
            return errors
        lines = lines[1:]
        lines[1] = f"In domain file, line {lines[1].strip().split(' ')[-1] if ' ' in lines[1] else lines[1]}"
        info = "\n".join(lines)
        return info.strip()

    return None

def problem_errors(domain_file: str, problem_file: str) -> str | None:
    """Check for problem errors."""

    if not os.path.exists(f"{loki_dir}/problem"):
        Logger.print(f"Could not find the Loki problem at '{loki_dir}/problem'")
        return None

    if domain_errors(domain_file) is not None:
        return None # We can't check for problem errors if the domain has errors

    try:
        subprocess.check_output([f"{loki_dir}/problem", domain_file, problem_file], stderr=subprocess.STDOUT).decode()
    except subprocess.CalledProcessError as exc:
        response = exc.output.decode().strip()
        if "<Signals.SIGABRT: 6>" in response:
            Logger.print("Loki could not find the domain or problem file.")
            return None
        errors = f"terminate called {response.split('terminate called',maxsplit=1)[1]}"
        lines = errors.split("\n")
        if len(lines) > 2:
            lines = lines[1:]
            if lines[1].strip().count(" ") > 0:
                lines[1] = f"In problem file, line {lines[1].strip().split(' ')[-1]}"
        info = "\n".join(lines)
        return info.strip()

    return None