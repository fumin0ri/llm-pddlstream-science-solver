import os, random
from typing import Iterable

from .utils.pddl_output_utils import combine_blocks
from .utils.paths import type_hierarchy_prompts as prompt_dir
from .utils.logger import Logger
from .utils.pddl_generator import PddlGenerator
from .utils.human_feedback import human_feedback
from .utils.llm_model import LLM_Chat, get_llm

class Hierarchy:
    class Node:
        def __init__(self, rows: list[str], depth: int = 0, parent = None):
            """
            Initializes a node in the hierarchy.

            Args:
                rows (list[str]): The list of rows. Each row starts has: 1 tab per depth, optionally a "- ", the name of the node and possibly comments after ":"
                depth (int, optional): The depth of the current node. Defaults to 0.
            """
            row = rows.pop(0).strip(" \t-\n") # pop itself and clean up
            self.name = row.split(':',1)[0].strip().replace(" ", "_") # Don't allow spaces in names
            self.comment = "" if ':' not in row else row.split(':',1)[1].strip()
            self.depth = depth
            self.children = []
            self.parent = parent
            #print(f"CREATING NODE: {self.name} with parent {parent} at depth {depth}")
            while len(rows) > 0:
                row = rows[0] # peek at the next row
                row_depth = row.split("-")[0].count('\t') # number of tabs gives depth
                if row_depth == depth + 1: # row is a child of this node
                    self.children.append(Hierarchy.Node(rows, depth + 1, parent = self))
                elif row_depth <= depth:
                    break # we've reached the end of this node's children
                else:
                    raise ValueError(f"At node [{row.strip()}] depth increases too heavily (to {row_depth} from {depth})")

        def is_subtype(self, object: str, type: str) -> bool | None:
            """Returns True if object is a subtype of type, False if not, and None if it isn't included in the hierarchy"""
            if self.name == type:
                return object in self
            for child in self.children:
                child_res = child.is_subtype(object, type)
                if child_res is not None:
                    return child_res
            return None

        def ancestors(self) -> list[str]:
            """Returns a list of all the ancestors of this node, including itself. Itself is last, root is first."""
            if self.parent is None:
                return [self.name]
            return self.parent.ancestors() + [self.name]

        def __contains__(self, object: str) -> bool:
            """Returns True if object is a child of this node, or the node itself, False if not"""
            if self.name == object:
                return True
            for child in self.children:
                if object in child:
                    return True
            return False

        def __iter__(self) -> iter:
            """Iterates through all the children of this node, including itself"""
            yield self
            for child in self.children:
                yield from child

        def __len__(self) -> int:
            return 1 + sum([len(child) for child in self.children])

        def __str__(self) -> str:
            return "\t"*self.depth + f"- {self.name}: {self.comment}"

    def __init__(self, hierarchy_str: str):
        """
        Initializes a hierarchy from a string, which should be formatted as a markdown list. See the example below.

        Example of a hierarchy string:
        - object: object is always root, everything is an object
            - vehicle: a thing that can transport people or goods
                - plane: a vehicle that can fly
            - country: a nation with its own government

        Args:
            hierarchy_str (str): The string representation of the hierarchy.
        """
        clean_str = hierarchy_str.strip()
        hierarchy_rows = clean_str.split('\n')
        hierarchy_rows = [row for row in hierarchy_rows if len(row.strip()) > 0] # remove empty rows
        self.root = self.Node(hierarchy_rows)

    def is_subtype(self, object: str, type: str) -> bool:
        """Returns True if object is a subtype of type, False if not. Error if type isn't included in the hierarchy.

        Args:
            object (str): The object to check if it is a subtype of type.
            type (str): The type to check if object is a subtype of.

        Raises:
            ValueError: If type isn't included in the hierarchy.
        """
        res = self.root.is_subtype(object, type)
        if res is None:
            raise ValueError(f'{type} is not included in the hierarchy')
        return res

    def types(self) -> list[str]:
        """Returns a list of all the types (names) in the hierarchy"""
        return [node.name for node in self]

    def replace_comments(self, type_comments: dict[str, str]):
        """Replaces the comments of the types in the hierarchy with the comments in the type_comments dictionary if therein.

        Args:
            type_comments (dict[str, str]): A dictionary with type names as keys and comments as values.
        """
        for node in self.root:
            if node.name in type_comments:
                node.comment = type_comments[node.name]

    def count(self, type: str) -> int:
        """Returns the number of times type appears in the hierarchy"""
        return sum([1 for node in self if node.name == type])

    def prune_to(self, to_keep: list[str]):
        """Prunes the hierarchy to only include the types in to_keep."""
        to_remove = []
        print(self)
        for node in self:
            # Keep any node that is a parent of a node to keep
            if not any([type in node for type in to_keep]):
                to_remove.append(node)
        for node in to_remove:
            if node.parent:
                # Remove the node from its parent, if it has one
                node.parent.children.remove(node)
        return self

    def type_list(self) -> str:
        """Returns a PDDL-formatted list of types"""
        desc = ""
        for node in self: # Due to the internal order parents always come before children
            if node.parent is None:
                continue # skip root
            desc += f"{node.name} - {node.parent.name} ; {node.comment}\n"
        return desc

    def contains(self, obj: str) -> bool:
        """Returns True if obj is included in the hierarchy"""
        return obj in self.root

    def ancestors(self, type: str) -> list[str]:
        """Returns a list of all the ancestors of type, including itself. Itself is last, root is first."""
        for node in self:
            if node.name == type:
                return node.ancestors()
        return []

    def shared_ancestor(self, type1: str, type2: str) -> str:
        """Returns the first shared ancestor of type1 and type2 (including themselves)"""
        type1_ancestors = self.ancestors(type1)
        type2_ancestors = self.ancestors(type2)
        for ancestor in reversed(type1_ancestors):
            if ancestor in type2_ancestors:
                return ancestor
        return None

    def explicit_hierarchy(self) -> str:
        text = ""
        for node in self:
            if node.parent:
                text += "- '" + node.name + "' is a/an '" + node.parent.name + "'\n"
        return text

    def overwrite_from_dicts(self, hierarchy_dict: dict[str, str], descriptions: dict[str, str]):
        """Overwrites the hierarchy with a dictionary representation of a hierarchy. The hierarchy is formated {'type': 'parent_type'}"""
        depths = {type: 0 for type in hierarchy_dict.keys()}
        for _ in range(len(hierarchy_dict)+1):
            # Guarantee that the depth can propagate through the hierarchy regardless of the order of the types
            for type, parent in hierarchy_dict.items():
                if type == "object":
                    continue # object is always root
                depths[type] = depths[parent] + 1
        # Create all the nodes
        nodes = {type: self.Node(
            [f"- {type}: {descriptions[type]}"], depth = depths[type]
        ) for type in hierarchy_dict.keys()}
        # Add the parents to each node
        for child, parent in hierarchy_dict.items():
            if child == "object":
                continue
            print(f"ADDING PARENT: {parent} to {child}")
            nodes[child].parent = nodes[parent]
            nodes[parent].children.append(nodes[child])
        self.root = nodes["object"]
        # We really hope the order holds, but it should :)

    def __str__(self, explicit: bool = True) -> str:
        base = "\n".join([str(node) for node in self])
        explicit_str = self.explicit_hierarchy()
        return f"{base}\n\n{explicit_str}" if explicit else base

    def __iter__(self) -> Iterable[Node]:
        """Iterates through all the nodes in the hierarchy"""
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

@Logger.section("2 Hierarchy Construction")
def hierarchy_construction(
        llm_conn: LLM_Chat,
        types: list[str],
        domain_desc: str,
        replace_comments = True,
        feedback = None,
        shuffle = False,
        retries = 0,
        force_include: bool = False,
        prune: bool = True,
        also_create_types: bool = False,
        validate_duplicates: bool = False,
    ) -> Hierarchy:
    llm_conn.reset_token_usage()

    if shuffle:
        types = random.sample(types, len(types))

    types = [type.lower().strip(" `") for type in types] # clean types
    types = [type.split(":",1)[0].replace(" ", "_") + ":" + type.split(":",1)[1] if ":" in type else type for type in types] # replace spaces with underscores in names

    if not also_create_types:
        with open(os.path.join(prompt_dir, 'main2.txt')) as f:
            hierarchy_prompt = f.read().strip()
    if also_create_types:
        with open(os.path.join(prompt_dir, 'main_with_creation.txt')) as f:
            hierarchy_prompt = f.read().strip()

    type_list = "- " + "\n- ".join(types) # add a dash to each object and place them on separate lines
    hierarchy_prompt = hierarchy_prompt.replace('{type_list}', type_list)
    hierarchy_prompt = hierarchy_prompt.replace('{domain_desc}', domain_desc if domain_desc is not None else "No description available")

    llm_output = llm_conn.get_response(prompt=hierarchy_prompt)
    llm_output = clean_llm_output(llm_output)

    # Process LLM output
    hierarchy = parse_hierarchy(llm_output)

    if force_include:
        # Check that all objects are included in the hierarchy
        for type in types:
            if type.split(':',1)[0].strip() not in hierarchy.types():
                if retries > 0:
                    Logger.print(f"Failed to include {type}. Retrying to construct the hierarchy with {retries} retries left")
                    return hierarchy_construction(llm_conn, types, domain_desc, shuffle = True, retries = retries - 1)
                raise KeyError(f'{type} is not included in the hierarchy')

    if feedback is not None:
        if feedback.lower() == "human":
            feedback_msg = human_feedback(f"\n\nThe hierarchy constructed is:\n{hierarchy}\n")
        else:
            if replace_comments:
                hierarchy.replace_comments({t.split(':',1)[0]: t.split(":",1)[1] for t in types if ":" in t})

            if not also_create_types:
                with open(os.path.join(prompt_dir, 'feedback2.txt')) as f:
                    feedback_prompt = f.read().strip()
            if also_create_types:
                with open(os.path.join(prompt_dir, 'feedback_with_creation.txt')) as f:
                    feedback_prompt = f.read().strip()
            feedback_prompt = feedback_prompt.replace('{type_hierarchy}', str(hierarchy))
            feedback_prompt = feedback_prompt.replace('{domain_desc}', domain_desc)

            feedback_msg = get_llm_feedback(llm_conn, feedback_prompt)

    # Check if any elements are included multiple times
    if validate_duplicates:
        duplicate_types = {}
        for type in hierarchy.types():
            if hierarchy.count(type) > 1:
                duplicate_types[type] = hierarchy.count(type)
        if len(duplicate_types) > 0:
            for type, count in duplicate_types.items():
                Logger.print(f"Included {type} {count} times in the hierarchy.")
                desc = f"{type} is included {count} times in the hierarchy. Please remove duplicates."
                feedback_msg = feedback_msg + "\n"*2 + desc if feedback_msg is not None else desc

    if feedback_msg is not None:
        messages = [
            {'role': 'user', 'content': hierarchy_prompt},
            {'role': 'assistant', 'content': llm_output},
            {'role': 'user', 'content': feedback_msg}
        ]
        llm_response = llm_conn.get_response(messages=messages)
        hierarchy = parse_hierarchy(llm_response)

    # Remove any leaf nodes that are not included in the types
    if prune:
        hierarchy.prune_to([t.split(':',1)[0] for t in types])

    # Check that no type is included twice
    for type in hierarchy.types():
        if hierarchy.count(type) > 1:
            if retries > 0 and validate_duplicates:
                Logger.print(f"Included {type} twice. Retrying to construct the hierarchy with {retries} retries left")
                return hierarchy_construction(llm_conn, types, domain_desc, shuffle = True, retries = retries - 1, force_include = force_include, prune = prune, also_create_types = also_create_types)
            raise ValueError(f'{type} is included multiple times in the hierarchy ({hierarchy.count(object)} times): \n{hierarchy}')

    # Replace the comments of the types in the hierarchy with the comments in the types list if therein
    if replace_comments:
        hierarchy.replace_comments({t.split(':',1)[0]: t.split(":",1)[1] for t in types if ":" in t})

    Logger.print(f"\n\nConstructed hierarchy with {len(hierarchy)} nodes:\n", hierarchy)
    PddlGenerator.set_types(hierarchy.type_list())

    in_tokens, out_tokens = llm_conn.token_usage()
    Logger.add_to_info(Hierarchy_Construction_Tokens=(in_tokens, out_tokens))

    return hierarchy

def parse_hierarchy(llm_output: str) -> Hierarchy:
    """Parses a hierarchy from the LLM output"""
    try:
        # Extract the markdown block content
        print(f"Input to parse_hierarchy:\n{'-'*30}\n{llm_output}\n{'-'*30}\n")
        if "```" in llm_output:
            print("Found ```")
            hierarchy_str = llm_output.split('```')[1].strip("\n")
        else:
            print("Didn't find ```")
            hierarchy_str = "-" + llm_output.split("## Hierarchy")[1].split('-', maxsplit=1)[1]
            hierarchy_str = "\n".join([row for row in hierarchy_str.split('\n') if row.strip().startswith('-')])
        # Exchange spaces for tabs
        hierarchy_str = hierarchy_str.replace(' '*4, '\t')
        hierarchy_str = hierarchy_str.strip(" \n")
        print(f"Initial from parse_hierarchy:\n{'-'*30}\n{hierarchy_str}\n{'-'*30}\n")

        # If the hierarchy doesn't with 'object' but is unindented, indent
        if not hierarchy_str.startswith('- object') and hierarchy_str.startswith('- '):
            print("Hierarchy doesn't start with 'object'. Indenting.")
            hierarchy_str = hierarchy_str.replace('- ', '\t- ')
        # Add - object to the beginning of the hierarchy, if it isn't already there
        if not hierarchy_str.startswith('- object') and hierarchy_str.startswith('\t- '):
            print("Hierarchy doesn't start with 'object'. Adding.")
            hierarchy_str = "- object : object is always root, everything is an object\n" + hierarchy_str

        print("HIERARCHY STR:------\n", hierarchy_str,"\n------\n")
        return Hierarchy(hierarchy_str)
    except Exception as e:
        Logger.print("Failed to parse hierarchy from LLM output.")
        return Hierarchy("Hierarchy could not parse. Please provide a valid hierarchy within a markdown block \"```\".")

def get_llm_feedback(llm_conn: LLM_Chat, feedback_prompt: str):
    feedback_output = llm_conn.get_response(feedback_prompt)
    if "no feedback" in feedback_output.lower() or len(feedback_output.strip()) == 0:
        Logger.print("FEEDBACK:\n", "No feedback.")
        return None
    else:
        if feedback_output.count("```") >= 2:
            feedback_output = feedback_output.split('```')[1].strip("\n")
        Logger.print("FEEDBACK:\n", feedback_output)
        feedback_output = "## Feedback" + feedback_output + "\nStart with a \"## Response\" header, then respond with the entire hierarchy below a \"## Hierarchy\" header as before."
        feedback_output += "\n\n## Response\n"
        return feedback_output

def clean_llm_output(llm_output: str) -> str:
    llm_output = llm_output.replace("```pddl", "```").replace("```PDDL", "```")
    llm_output = llm_output.replace("```markdown", "```")
    return llm_output