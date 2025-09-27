import os

from .logger import Logger
from .paths import results_dir
from .pddl_types import Action, Predicate

class PddlGeneratorClass:
    def __init__(self):
        self.started = False

    def start(self, experiment = None, domain = None):
        self.started = True

        # Get experiment name if not specified
        if experiment is None:
            if not Logger.started:
                raise FileNotFoundError("Logger not started and no experiment specified. Start logger or specify experiment when starting PDDLGenerator.")
            experiment = Logger.name
        if domain is None:
            if not Logger.started:
                raise FileNotFoundError("Logger not started and no domain specified. Start logger or specify domain when starting PDDLGenerator.")
            domain = Logger.domain
        
        # Initialize files
        os.makedirs(os.path.join(results_dir, experiment), exist_ok=True)
        self.domain_file = os.path.join(results_dir, experiment, "domain.pddl")
        self.problem_file = os.path.join(results_dir, experiment, "problem.pddl")

        # Initialize parts
        self.domain = domain
        self.types = ""
        self.predicates = ""
        self.actions = []
        self.objects = ""
        self.init = ""
        self.goal = ""
        self.overwritten_domain = None
        self.overwritten_problem = None

    def add_action(self, action: Action):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding action.")
            return
        self.actions.append(action)

    def reset_actions(self):
        self.actions = []

    def set_types(self, types: str):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding types.")
            return
        self.types = types.strip()
    
    def set_predicates(self, predicates: str):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding predicates.")
            return
        self.predicates = predicates

    def set_objects(self, objects: str):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding objects.")
            return
        self.objects = objects
    
    def set_init(self, init: str):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding init.")
            return
        self.init = init

    def set_goal(self, goal: str):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding goal.")
            return
        self.goal = goal

    def get_objects(self):
        if not self.started:
            print("Warning: PDDLGenerator not started. Returning nothing.")
            return ""
        return self.objects
    
    def get_init(self):
        if not self.started:
            print("Warning: PDDLGenerator not started. Returning nothing.")
            return ""
        return self.init

    def get_goal(self):
        if not self.started:
            print("Warning: PDDLGenerator not started. Returning nothing.")
            return ""
        return self.goal

    def generate(self):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before generating.")
        domain = self.generate_domain(self.domain, self.types, self.predicates, self.actions)
        problem = self.generate_problem(self.domain, self.objects, self.init, self.goal)
        with open(self.domain_file, "w") as f:
            f.write(domain)
        with open(self.problem_file, "w") as f:
            f.write(problem)
        return domain, problem

    def generate_domain(self, domain: str, types: str, predicates: str, actions: list[Action], allow_overwrite = True):        
        if self.overwritten_domain is not None and allow_overwrite:
            return self.overwritten_domain

        # Write domain file
        desc = ""
        desc += f"(define (domain {domain})\n"
        desc += self.indent(f"(:requirements\n   :strips :typing :equality :negative-preconditions :disjunctive-preconditions\n   :universal-preconditions :conditional-effects :existential-preconditions\n)", 1) + "\n\n"
        desc += f"   (:types \n{self.indent(types)}\n   )\n\n"
        desc += f"   (:predicates \n{self.indent(predicates)}\n   )"
        desc += self.action_descs(actions)
        desc += "\n)"
        desc = desc.lower() # The python PDDL package can't handle capital AND and OR
        return desc
    
    def action_descs(self, actions = None) -> str:
        if actions is None:
            actions = self.actions
        desc = ""
        for action in actions:
            desc += "\n\n" + self.indent(self.action_desc(action),1)
        return desc

    def generate_problem(self, domain: str, objects: str, init: str, goal: str, allow_overwrite = True):
        if self.overwritten_problem is not None and allow_overwrite:
            return self.overwritten_problem
        
        # Write problem file
        desc = "(define\n"
        desc += f"   (problem {domain}_problem)\n"
        desc += f"   (:domain {domain})\n\n"
        desc += f"   (:objects \n{self.indent(objects)}\n   )\n\n"
        desc += f"   (:init\n{self.indent(init)}\n   )\n\n"
        desc += f"   (:goal\n{self.indent(goal)}\n   )\n\n"
        desc += ")"
        desc = desc.lower() # The python PDDL package can't handle capital AND and OR
        return desc

    def indent(self, string: str, level: int = 2):
        return "   " * level + string.replace("\n", f"\n{'   ' * level}")
    
    def action_desc(self, action: Action):
        param_str = "\n".join([f"{name} - {type}" for name, type in action['parameters'].items()]) # name includes ?
        desc  = f"(:action {action['name']}\n"
        desc += f"   :parameters (\n{self.indent(param_str,2)}\n   )\n"
        desc += f"   :precondition\n{self.indent(action['preconditions'],2)}\n"
        desc += f"   :effect\n{self.indent(action['effects'],2)}\n"
        desc +=  ")"
        return desc
    
    def get_domain(self):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before getting domain file.")
        if self.overwritten_domain is not None:
            return self.overwritten_domain
        self.generate()
        with open(self.domain_file, "r") as f:
            return f.read()
        
    def get_problem(self):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before getting problem file.")
        if self.overwritten_problem is not None:
            return self.overwritten_problem
        self.generate()
        with open(self.problem_file, "r") as f:
            return f.read()
    
    def copy(self, other: "PddlGeneratorClass"):
        self.started = other.started
        #self.domain_file = other.domain_file
        #self.problem_file = other.problem_file
        #self.domain = other.domain
        self.types = other.types
        self.predicates = other.predicates
        self.actions = other.actions
        self.objects = other.objects
        self.init = other.init
        self.goal = other.goal
        # Since the overwritten parts are new, older versions of the generator should not have them
        self.overwritten_domain = other.overwritten_domain if hasattr(other, "overwritten_domain") else None
        self.overwritten_problem = other.overwritten_problem if hasattr(other, "overwritten_problem") else None

    def overwrite_domain(self, domain: str):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before overwriting domain.")
        self.overwritten_domain = domain.lower()
    
    def overwrite_problem(self, problem: str):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before overwriting problem.")
        self.overwritten_problem = problem.replace("AND","and").replace("OR","or")
        
    def single_action_domain(self, action: Action, predicates: list[Predicate]) -> str:
        predicate_str = "\n".join([pred["clean"].replace(":", " ; ",1) for pred in predicates])
        domain_str = self.generate_domain("SAD", self.types, predicate_str, [action])
        sad_file = os.path.join(os.path.dirname(self.domain_file), "sad.pddl")
        with open(sad_file, "w") as f:
            f.write(domain_str)
        return sad_file
    
PddlGenerator = PddlGeneratorClass()