import os, subprocess

from .logger import Logger
from .paths import val_dir

def domain_errors(domain_file: str) -> str | None:
    """Check for domain errors."""

    parse_errors = parse_domain(domain_file)
    if parse_errors is not None:
        # If the main parser fails, planrec will not be able to run
        return parse_errors

    planrec_errors = planrec_domain(domain_file)
    if planrec_errors is not None:
        return planrec_errors

    return None

def problem_errors(domain_file: str, problem_file: str) -> str | None:
    """Check for problem errors."""

    if parse_domain(domain_file) is not None:
        Logger.print("Error: Domain file is invalid. Skipping problem file VAL-idation.", subsection=False)
        return None

    parse_errors = parse_problem(domain_file, problem_file)
    if parse_errors is not None:
        return parse_errors

    planrec_errors = planrec_problem(domain_file, problem_file)
    if planrec_errors is not None:
        return planrec_errors

    return None

def parse_domain(domain_file: str) -> str | None:
    """Validate domain file."""

    if not os.path.exists(f"{val_dir}/Parser"):
        Logger.print(f"Could not find the VAL parser at '{val_dir}/Parser'", subsection=False)
        return None
    result = subprocess.check_output([f"{val_dir}/Parser", domain_file]).decode()

    if "Errors: 0" not in result:
        lines = result.split("Errors:")[1].split("\n")[1:]
        lines = [line.split(": ", maxsplit=1)[1].strip() for line in lines if len(line) > 0]
        Logger.print(f"Error VAL parsing domain file '{domain_file}':\n", "\n\t".join(lines), subsection=False)
        error = "\n".join(lines)
    else:
        error = None

    return error

def parse_problem(domain_file: str, problem_file: str) -> str | None:
    """Validate problem file."""

    if not os.path.exists(f"{val_dir}/Parser"):
        Logger.print(f"Could not find the VAL parser at '{val_dir}/Parser'", subsection=False)
        return None
    if parse_domain(domain_file) is not None:
        Logger.print("Error: Domain file is invalid. Skipping problem file VAL-idation.", subsection=False)
        return None

    result = subprocess.check_output([f"{val_dir}/Parser", domain_file, problem_file]).decode()

    if "Errors: 0" not in result:
        lines = result.split("Errors:")[1].split("\n")[1:]
        if any(["domain.pddl" in line for line in lines]):
            # If there are any domain errors, we just give up?
            Logger.print("VAL encountered domain errors. Giving up on problem file.", subsection=False)
            return None
        lines = [line.split(": ", maxsplit=1)[1].strip() for line in lines if len(line) > 0]
        Logger.print(f"Error VAL parsing problem file '{problem_file}':\n", "\n\t".join(lines), subsection=False)
        error = "\n".join(lines)
    else:
        error = None

    return error


def planrec_domain(domain_file: str) -> str:
    """Spoof planrec to validate the domain file."""

    if not os.path.exists(f"{val_dir}/PlanRec"):
        Logger.print("Error: Could not find VAL PlanRec at '{val_dir}/PlanRec'", subsection=False)
        return None

    # Create a temporary problem file
    problem_file = os.path.join(os.path.dirname(domain_file), "temp_problem.pddl")
    with open(problem_file, "w") as f:
        f.write("(define (problem spoof_problem) (:domain spoof_domain) (:objects) (:init) (:goal (spoof_goal)))")

    try:
        result = subprocess.check_output([f"{val_dir}/PlanRec", domain_file, problem_file]).decode()
        os.remove(problem_file)
    except Exception as e:
        # Since the problem is a spoof, we expect an error. However, types are checked *before* this crash, so we can check for type errors.
        os.remove(problem_file)
        return None

    if "fail type-checking" in result:
        Logger.print("Error: Type error found in domain or problem file.", subsection=False)
        section = "\n".join(result.strip().split("\n")[-3:])
        return section

    return None

def planrec_problem(domain_file: str, problem_file: str) -> str:
    """Spoof planrec to validate the problem file."""

    if not os.path.exists(f"{val_dir}/PlanRec"):
        Logger.print("Error: Could not find VAL PlanRec at '{val_dir}/PlanRec'", subsection=False)
        return None

    if planrec_domain(domain_file) is not None:
        Logger.print("Error: Domain file is invalid. Skipping problem file PlanRec.", subsection=False)
        return None

    try:
        result = subprocess.check_output([f"{val_dir}/PlanRec", domain_file, problem_file]).decode()
    except Exception as e:
        # If the parser crashes, the types *should* have been checked before this point.
        return None

    if "Type problem" in result:
        Logger.print("Error: Type error found in domain or problem file.", subsection=False)
        section = "\n".join(result.strip().split("\n")[-3:])
        return section

    return None

# ---------------------------------------------------------------------
# The below is available, but not used in the current implementation
# ---------------------------------------------------------------------

def analyse(domain_file: str, problem_file: str) -> str:
    """Analyse domain and problem files."""

    if not os.path.exists(f"{val_dir}/Analyse"):
        raise FileNotFoundError(f"Could not find the VAL parser at '{val_dir}/Analyse'")
    result = subprocess.check_output([f"{val_dir}/Analyse", domain_file, problem_file]).decode()

    return result

def how_what_when(domain_file: str, problem_file: str) -> str:

    if not os.path.exists(f"{val_dir}/HowWhatWhen"):
        raise FileNotFoundError(f"Could not find the VAL parser at '{val_dir}/HowWhatWhen'")
    result = subprocess.check_output([f"{val_dir}/HowWhatWhen", domain_file, problem_file]).decode()

    return result

def tim(domain_file: str, problem_file: str) -> str:

    if not os.path.exists(f"{val_dir}/TIM"):
        raise FileNotFoundError(f"Could not find the VAL parser at '{val_dir}/TIM'")
    result = subprocess.check_output([f"{val_dir}/TIM", domain_file, problem_file]).decode()

    return result

def validate_domain(domain_file: str) -> str:

    if not os.path.exists(f"{val_dir}/Validate"):
        raise FileNotFoundError(f"Could not find the VAL parser at '{val_dir}/Validate'")
    try:
        result = subprocess.check_output([f"{val_dir}/Validate", domain_file]).decode()
    except subprocess.CalledProcessError as e:
        result = e.output.decode()

    return result

def validate_problem(domain_file: str, problem_file: str) -> str:

    if not os.path.exists(f"{val_dir}/Validate"):
        raise FileNotFoundError(f"Could not find the VAL parser at '{val_dir}/Validate'")
    result = subprocess.check_output([f"{val_dir}/Validate", domain_file, problem_file]).decode()

    return result