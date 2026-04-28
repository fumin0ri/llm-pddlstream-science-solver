import os, subprocess

from .paths import cpddl_path
from .logger import Logger

def domain_errors(domain_file):
    """
    Returns the errors in the domain file.
    """

    if not os.path.exists(cpddl_path):
        Logger.print(f"Could not find cpddl at '{cpddl_path}'")
        return None

    dummy_problem = "(define (problem dummy) (:domain dummy) (:objects) (:init) (:goal (and)))"

    temp_file = os.path.join(os.path.dirname(domain_file), "temp_problem.pddl")
    with open(temp_file, "w") as f:
        f.write(dummy_problem)

    try:
        # Add a memory limit, since cpddl can get stuck normalizing some problems a long time. 5mb is enough for validation on test problems, so 20mb should be enough for most problems
        subprocess.check_output(["apptainer", "run", cpddl_path, "--pddl-stop", "--max-mem", "20", domain_file, temp_file], stderr=subprocess.STDOUT)
        error = None
    except subprocess.CalledProcessError as exc:
        result = exc.output.decode().strip()
        if "Error:" not in result:
            return None # Some other error occured, likely it ran out of memory during normalization
        section = "Domain Error: " + result.split("Error:")[1].split("Traceback")[0].strip()
        lines = section.split("\n")
        # Remove line 2
        lines = lines[:1] + lines[2:]
        error = "\n".join(lines)

    # Remove the dummy problem file
    os.remove(temp_file)

    return error

def problem_errors(domain_file, problem_file):
    """
    Returns the errors in the problem file.
    """

    if not os.path.exists(cpddl_path):
        Logger.print(f"Could not find cpddl at '{cpddl_path}'")
        return None

    if domain_errors(domain_file) is not None:
        return None # We can't check for problem errors if the domain has errors

    temp_file = os.path.join(os.path.dirname(problem_file), "temp_problem.pddl")
    with open(temp_file, "w") as f:
        in_init = False
        with open(problem_file, "r") as p:
            for line in p:
                if "(:init" in line:
                    in_init = True
                if "(:goal" in line:
                    in_init = False
                if "not " in line.split(";")[0] and in_init:
                    line = ";" + line # Comment out negative literals, not supported by cpddl
                f.write(line)

    try:
        # Add a memory limit, since cpddl can get stuck normalizing some problems a long time. 5mb is enough for validation on test problems, so 20mb should be enough for most problems
        subprocess.check_output(["apptainer", "run", cpddl_path, "--pddl-stop", "--max-mem", "20",  domain_file, temp_file], stderr=subprocess.STDOUT)
        error = None
    except subprocess.CalledProcessError as exc:
        result = exc.output.decode().strip()
        if "Error:" not in result:
            os.remove(temp_file)
            return None # Some other error occured, likely it ran out of memory during normalization
        section = "Problem Error: " + result.split("Error:")[1].split("Traceback")[0].strip()
        lines = section.split("\n")
        # Remove line 2
        lines = lines[:1] + lines[2:]
        # If the lines were changed to comments, remove the comments
        lines = [line.replace(";","",1) if (";" in line and line.index(";") == 9) else line for line in lines]
        error = "\n".join(lines)

    # Remove the dummy problem file
    os.remove(temp_file)
    return error