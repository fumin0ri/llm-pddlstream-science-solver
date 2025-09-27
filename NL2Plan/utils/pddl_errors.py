import traceback

from .val import domain_errors as val_domain_errors
from .val import problem_errors as val_problem_errors

from .loki import domain_errors as loki_domain_errors
from .loki import problem_errors as loki_problem_errors

from pddl import parse_domain as py_parse_domain
from pddl import parse_problem as py_parse_problem

from .paranthesis_parser import errors as paranthesis_errors

from .cpddl import domain_errors as cpddl_domain_errors
from .cpddl import problem_errors as cpddl_problem_errors

from .logger import Logger

def domain_errors(domain_file: str, VAL: bool = True, py: bool = False, Loki: bool = True, cppdl: bool = True, paran: bool = True) -> str | None:
    errors = {}

    if py:
        try:
            py_parse_domain(domain_file)
        except Exception as e:
            Logger.print(f"Error PY parsing domain file '{domain_file}': {str(e)}", subsection=False)
            errors["py"] = str(e)

    if VAL:
        try:
            val_error = val_domain_errors(domain_file)
            if val_error is not None:
                Logger.print(f"Error VAL parsing domain file '{domain_file}':\n{val_error}", subsection=False)
                errors["val"] = val_error
        except Exception as e:
            error_str = traceback.format_exc()
            Logger.print(f"Error VAL parsing domain file '{domain_file}':\n{error_str}", subsection=False)

    if Loki:
        try:
            loki_error = loki_domain_errors(domain_file)
            if loki_error is not None:
                Logger.print(f"Error Loki parsing domain file '{domain_file}':\n{loki_error}", subsection=False)
                errors["loki"] = loki_error
        except Exception as e:
            error_str = traceback.format_exc()
            Logger.print(f"Error Loki parsing domain file '{domain_file}':\n{error_str}", subsection=False)

    if cppdl:
        try:
            cppdl_error = cpddl_domain_errors(domain_file)
            if cppdl_error is not None:
                Logger.print(f"Error cpddl parsing domain file '{domain_file}':\n{cppdl_error}", subsection=False)
                errors["cppdl"] = cppdl_error
        except Exception as e:
            error_str = traceback.format_exc()
            Logger.print(f"Error cpddl parsing domain file '{domain_file}':\n{error_str}", subsection=False)

    if paran:
        try:
            paranthesis_error = paranthesis_errors(domain_file)
            if paranthesis_error is not None:
                Logger.print(f"Error paran parsing domain file '{domain_file}':\n{paranthesis_error}", subsection=False)
                errors["paran"] = paranthesis_error
        except Exception as e:
            error_str = traceback.format_exc()
            Logger.print(f"Error paran parsing domain file '{domain_file}':\n{error_str}", subsection=False)

    if len(errors) == 0:
        return None

    if len(errors) == 1:
        # Sometimes one VAL or Paran might make a mistake. In that case, we ignore the error
        # VAL generally fails alone if we use some strange keyword, like declaring "within" as a predicate
        if "val" in errors or "paran" in errors:
            return None

    error = "\n\n".join([v for v in errors.values()])

    return error

def problem_errors(problem_file: str, domain_file: str, VAL: bool = True, py: bool = False, Loki: bool = True, cppdl: bool = True, paran: bool = True) -> str | None:
    # Note that pddl package does not support `forall` and `exists` quantifiers in goals
    error = None

    if py:
        try:
            py_parse_problem(problem_file)
        except Exception as e:
            Logger.print(f"Error PY parsing problem file '{problem_file}': {str(e)}", subsection=False)
            error = str(e) if error is None else f"{error}\n{str(e)}"

    if VAL:
        val_error = val_problem_errors(domain_file, problem_file)
        if val_error is not None:
            Logger.print(f"Error VAL parsing problem file '{problem_file}':\n{val_error}", subsection=False)
            error = val_error if error is None else f"{error}\n{val_error}"

    if Loki:
        loki_error = loki_problem_errors(domain_file, problem_file)
        if loki_error is not None:
            Logger.print(f"Error Loki parsing problem file '{problem_file}':\n{loki_error}", subsection=False)
            error = loki_error if error is None else f"{error}\n{loki_error}"

    if cppdl:
        cppdl_error = cpddl_problem_errors(domain_file, problem_file)
        if cppdl_error is not None:
            Logger.print(f"Error cpddl parsing problem file '{problem_file}':\n{cppdl_error}", subsection=False)
            error = cppdl_error if error is None else f"{error}\n{cppdl_error}"

    if error and paran:
        # Paranthesis is only checked if there is an error in the file, since it's less sophisticated. However, if the others can't check we still do
        paranthesis_error = paranthesis_errors(problem_file)
        if paranthesis_error is not None:
            Logger.print(f"Error paran parsing problem file '{problem_file}':\n{paranthesis_error}", subsection=False)
            error = paranthesis_error if error is None else f"{error}\n{paranthesis_error}"

    return error