from copy import deepcopy
import traceback
from typing import Literal

from .logger import Logger
from .pddl_output_utils import parse_params, parse_new_predicates, parse_predicates, read_object_types

class PDDL_Syntax_Validator:
    def __init__(self,
        obj_hierarchy,
        error_types=None,
        messed_output_len=20,
        unsupported_keywords=None,
    ):
        default_unsupported = {'if': "`if` can generally be replaced with `imply` if in the preconditions or `when` in the effects.",}
        self.unsupported_keywords = default_unsupported if unsupported_keywords is None else unsupported_keywords
        self.messed_output_len = messed_output_len
        self.obj_types = [t.lower() for t in obj_hierarchy.types()]
        self.obj_hierarchy = obj_hierarchy

    def perform_validation(self, llm_output, **kwargs):
        errors = []
        functions = [
            self.check_header_specification,
            self.check_keyword_usage,
            self.check_num_parantheses,
            self.check_param_types,
            self.check_predicate_names,
            self.check_predicate_format,
            self.check_predicate_usage,
        ]
        for func in functions:
            try:
                validation_info = func(llm_output, **kwargs)
            except Exception as e:
                Logger.print(f"Error in function {func.__name__}:\n\t{e}")
                continue
            if not validation_info[0]:
                errors.append(validation_info)
        errors = [e for e in errors if str(e[3]) != 'None']
        if len(errors) > 0:
            funcs = " ".join([str(error[1]) for error in errors])
            keys  = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n\n".join([str(error[3]) for error in errors])
            return False, funcs, keys, msgs
        return True, 'all_validation_pass', None, None

    def check_header_specification(self, llm_output, **kwargs):
        """
        This function checks whether the header is correctly specified
        """
        errors = []
        llm_output = "\n" + llm_output # Add a newline in case it starts directly with the header
        for header in ['\n### Action Parameters', '\n### Action Preconditions', '\n### Action Effects', '\n### New Predicates']:
            if (not header in llm_output) and (not header.replace('\n###', '\n####') in llm_output):
                feedback_message = f'The header `{header}` is missing in the PDDL model. Please include the header `{header.strip()}` in the PDDL model.'
                errors.append([False, 'header_specification', header, feedback_message])
        for header in ['\n### Action Parameters', '\n### Action Preconditions', '\n### Action Effects']:
            if (not header in llm_output) and (not header.replace('\n###', '\n####') in llm_output):
                continue # We don't need to check the code block if the header is missing
            if not header in llm_output:
                header = header.replace('\n###', '\n####') # We know one of the two is present, so we can just switch the two
            if llm_output.split(f"{header}")[1].split("##")[0].count('```') < 2:
                feedback_message = f'The header `{header}` is missing a formalised code block. Please include a "```" block in the `{header}` section.'
                errors.append([False, 'header_specification', header, feedback_message])
        if len(errors) > 0:
            headers = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n".join([str(error[3]) for error in errors])
            return False, 'header_specification', headers, msgs
        return True, 'header_specification', None, None

    def check_unsupported_keywords(self, llm_output, **kwargs):
        """
        A simple function to check whether the pddl model uses unsupported logic keywords
        """
        errors = []
        for keyword, hint in self.unsupported_keywords.items():
            if f'({keyword} ' in llm_output:
                feedback_message = f'The precondition or effect contain the keyword `{keyword}` that is not supported in a standard STRIPS style model. Please express the same logic in a simplified way. You can come up with new predicates if needed (but note that you should use existing predicates as much as possible). {hint}'
                errors.append([False, 'has_unsupported_keywords', keyword, feedback_message])
                continue
        if len(errors) > 0:
            keywords = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n".join([str(error[3]) for error in errors])
            return False, 'has_unsupported_keywords', keywords, msgs
        return True, 'has_unsupported_keywords', None, None

    def check_keyword_usage(self, llm_output, **kwargs):
        llm_output = "\n" + llm_output

        banned_keywords = {
            "\n### Action Preconditions": ["when ", "if ", "implies "],
            "\n### Action Effects": ["exists ", "if ", "implies ", "imply "],
        }

        hints = {
            "when ": "You can generally replace `when` with `imply` in the preconditions.",
            "exists ": "You can generally replace `exists` with a combination `forall` and `when` in the effects.",
            "if ": "You can generally replace `if` with `imply` in the preconditions or `when` in the effects.",
            "implies ": "You can generally replace `implies` with `imply` in the preconditions or `when` in the effects.",
            "imply ": "You can generally replace `imply` with `when` in the effects.",
        }

        errors = []
        for heading in ['\n### Action Preconditions', '\n### Action Effects']:
            if (not heading in llm_output) and (not heading.replace('\n###', '\n####') in llm_output):
                errors.append([False, 'heading_not_found', None, f'The header `{heading.strip()}` is missing in the PDDL model. Please include the header `{heading.strip()}` in the PDDL model.'])
                continue
            if not heading in llm_output:
                heading = heading.replace('\n###', '\n####') # We know one of the two is present, so we can just switch the two
            if not "```" in llm_output.split(heading)[1]:
                errors.append([False, 'code_not_found', None, f'The header `{heading.strip()}` is missing a formalised code block. Please include a "```" block in the `{heading.strip()}` section.'])
                continue

            content = llm_output.split(heading)[1].split("```")[1].strip()
            # remove comments
            content = "\n".join([line.split(";")[0] for line in content.split("\n") if line.strip() != ""])

            for keyword in banned_keywords[heading.replace("####", "###")]: # We might need to replace the header to match the keys in banned_keywords
                if keyword in content:
                    feedback_message = f'The keyword `{keyword}` is not supported in the `{heading.strip()}` section. ' + hints.get(keyword, "")
                    errors.append([False, 'invalid_effect_keyword', keyword, feedback_message])

        if len(errors) > 0:
            keywords = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n".join([str(error[3]) for error in errors])
            return False, 'invalid_effect_keyword', keywords, msgs
        return True, 'invalid_effect_keyword', None, None

    def check_num_parantheses(self, llm_output, **kwargs):
        """
        This function checks whether the number of opening and closing parantheses are the same
        """
        errors = []
        for header in ['Parameters', 'Preconditions', 'Effects', 'New Predicates']:
            if llm_output.split(f"{header}")[1].split("##")[0].count('(') != llm_output.split(f"{header}")[1].split("##")[0].count(')'):
                feedback_message = f'The number of opening and closing parentheses in the {header} section are not the same. Please make sure that the number of opening and closing parentheses are the same.'
                errors.append([False, 'num_parantheses', header, feedback_message])
        if len(errors) > 0:
            headers = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n".join([str(error[3]) for error in errors])
            return False, 'num_parantheses', headers, msgs
        return True, 'num_parantheses', None, None

    def check_messed_output(self, llm_output, **kwargs):
        """
        Though this happens extremely rarely, the LLM (even GPT-4) might generate messed-up outputs (basically
            listing a large number of predicates in preconditions and effects)
        """
        assert 'Preconditions' in llm_output, llm_output
        precond_str = llm_output.split('Preconditions')[1].split('```')[1].strip(" `\n:")
        if len(precond_str.split('\n')) > self.messed_output_len:
            feedback_message = f'You seem to have generated an action model with an unusually long list of preconditions. Please include only the relevant preconditions/effects and keep the action model concise.'
            return False, 'messed_output_feedback', None, feedback_message

        return True, 'messed_output_feedback', None, None

    def check_param_types(self, llm_output, **kwargs):
        errors = []
        params_info = parse_params(llm_output, include_internal=True)
        for param_name in params_info:
            param_type = params_info[param_name]
            if param_type not in self.obj_types:
                feedback_message = f'There is an invalid object type `{param_type}` for the parameter {param_name}. Remember to respond in the "- {{parameter name}} - {{parameter type}}: {{parameter description}}" format. Please revise the PDDL model to fix this error. '
                errors.append([False, 'invalid_object_type', param_name, feedback_message])
        if len(errors) > 0:
            params = " ".join([str(error[2]) for error in errors if error[2] is not None])
            msgs  = "\n".join([str(error[3]) for error in errors])
            return False, 'invalid_object_type', params, msgs
        return True, 'invalid_object_type', None, None

    def check_predicate_names(self, llm_output, generalize_predicate_types: Literal["dissallow", "allow", "return"] = "dissallow", **kwargs):
        to_return = []

        curr_predicates = kwargs['curr_predicates']
        curr_pred_dict = {pred['name'].lower(): pred for pred in curr_predicates}
        new_predicates = parse_new_predicates(llm_output)

        # check name clash with obj types
        invalid_preds = list()
        for new_pred in new_predicates:
            if new_pred['name'].lower() in self.obj_types:
                invalid_preds.append(new_pred['name'])
        if len(invalid_preds) > 0:
            feedback_message = f'The following predicate(s) have the same name(s) as existing object types:'
            for pred_i, pred_name in enumerate(list(invalid_preds)):
                feedback_message += f'\n{pred_i + 1}. {pred_name}'
            feedback_message += '\nPlease rename these predicates.'
            return False, 'invalid_predicate_names', None, feedback_message

        # check name clash with existing predicates
        duplicated_predicates = list()
        for new_pred in new_predicates:
            # check if the name is already used
            if new_pred['name'].lower() in curr_pred_dict:
                curr = curr_pred_dict[new_pred['name'].lower()]
                if len(curr['params']) == len(new_pred['params']):
                    # If the new predicates are the same, or a lower version of the existing predicates, it's not a problem
                    for i, (t1, t2) in enumerate(zip(curr['params'].values(), new_pred['params'].values())):
                        if not self._is_valid_type(t1, t2):
                            # Once we find a type that is not a subtype of the existing type, we can found a problem
                            break
                    else:
                        continue # If all types are lower, or the same, then it's not a problem
                    # if the new predicate is a "lower" version of the existing predicate, no problem
                if len(curr['params']) == len(new_pred['params']) and generalize_predicate_types != "dissallow":
                    # if we allow type generalization, we can always generalize the types to match
                    # so we only need to check if the number of parameters is the same
                    if generalize_predicate_types == "return":
                        to_return.append(new_pred)
                    continue
                duplicated_predicates.append((new_pred['raw'], curr_pred_dict[new_pred['name'].lower()]['raw']))

        if generalize_predicate_types == "return":
            return to_return

        if len(duplicated_predicates) > 0:
            feedback_message = f'The following predicate(s) have the same name(s) as existing predicate(s):'
            for pred_i, duplicated_pred_info in enumerate(duplicated_predicates):
                new_pred_full, existing_pred_full = duplicated_pred_info
                feedback_message += f'\n{pred_i + 1}. {new_pred_full.replace(":", ",",1)}; existing predicate with the same name: {existing_pred_full.replace(":", ",",1)}'
            feedback_message += "\n\nWhile you should reuse existing predicates, they need to retain their parameters if you do so. If existing predicates are not enough and you are devising new predicate(s), please use names that are different from existing ones. If you're redefining an existing predicate with different parameters, for example because it previously included a parameter of type `object` that is now removed, the predicate must still be renamed. In that situation, you should not use the old predicate but instead create a new one with a different name, such as `new_{predicate_name}`, even though the old predicate might already model the same property."
            feedback_message += '\n\nPlease revise the PDDL model to fix this error.\n\n'
            return False, 'invalid_predicate_names', None, feedback_message

        return True, 'invalid_predicate_names', None, None

    def check_predicate_format(self, llm_output, **kwargs):
        """
        Though this happens rarely, the LLM (even GPT-4) might forget to define the object type of some parameters in new predicates
        """
        errors = []
        new_predicates = parse_new_predicates(llm_output)
        for new_pred in new_predicates:
            new_pred_def = new_pred['raw'].split(':',1)[0]
            new_pred_def = new_pred_def.strip(" ()`")   # discard parentheses and similar
            split_predicate = new_pred_def.split(' ')[1:]   # discard the predicate name
            split_predicate = [e for e in split_predicate if e != '']

            for i, p in enumerate(split_predicate):
                if i % 3 == 0:
                    if '?' not in p:
                        feedback_message = f'There are syntax errors in the definition of the new predicate ({new_pred_def}). Please revise its definition and output the entire PDDL action model again. Note that you need to strictly follow the syntax of PDDL.'
                        errors.append([False, 'invalid_predicate_format', None, feedback_message])
                        continue
                    else:
                        if (i + 1 >= len(split_predicate) or split_predicate[i+1] != '-') or \
                           (i + 2 >= len(split_predicate)):
                            feedback_message = f'There are syntax errors in the definition of the new predicate ({new_pred_def}). Please revise its definition and output the entire PDDL action model again. Note that you need to define the object type of each parameter and strictly follow the syntax of PDDL.'
                            errors.append([False, 'invalid_predicate_format', None, feedback_message])
                            continue
                        param_obj_type = split_predicate[i+2]
                        if param_obj_type not in self.obj_types:
                            feedback_message = f'There is an invalid object type `{param_obj_type}` for the parameter {p} in the definition of the new predicate {new_pred_def}. Please revise its definition and output the entire PDDL action model again.'
                            errors.append([False, 'invalid_predicate_format', None, feedback_message])
        if len(errors) > 0:
            feedback_message = "\n".join([error[3] for error in errors])
            return False, 'invalid_predicate_format', None, feedback_message
        return True, 'invalid_predicate_format', None, None

    def check_new_action_creation(self, llm_output, **kwargs):
        """
        This action checks if the LLM attempts to create a new action (so two or more actions defined in the same response)
        """
        if llm_output.count('## Action Parameters') > 1 or llm_output.count('## Preconditions') > 1 or llm_output.count('## Effects') > 1 or llm_output.count('## New Predicates') > 1:
            # Note that the '##' check also covers the case with three #s for the headings
            feedback_message = "It's not possible to create new actions at this time. Please only define the requested action."
            return False, 'new_action_creation', None, feedback_message
        return True, 'new_action_creation', None, None

    def _is_valid_type(self, target_type, curr_type):
        return self.obj_hierarchy.is_subtype(curr_type, target_type)

    def _check_predicate_usage_pddl(
            self,
            pddl_snippet,
            predicate_list,
            action_params,
            part='preconditions',
            type_generalization: Literal["allow", "disallow", "return"] = "disallow"
        ):
        """
        This function checks three types of errors:
            - check if the num of params given matches the num of params in predicate definition
            - check if there is any param that is not listed under `Parameters:` (i.e. they're unknown)
            - check if the param type matches that in the predicate definition (if type_generalization is "disallow")

        If type_generalization is "return", the function will still check the above errors, but will return a dict of which param types need to be generalized
        in what manner to allow the PDDL model to be valid if the number of params is valid and the parameters all are defined.
        """
        errors = []
        preds_to_generalize = dict() # Only used if type_generalization is "return"
        def get_ordinal_suffix(_num):
            return {1: 'st', 2: 'nd', 3: 'rd'}.get(_num % 10, 'th') if _num not in (11, 12, 13) else 'th'

        Logger.log("Checking predicate usage in ", part, subsection=True)

        pred_names = {predicate_list[i]['name']: i for i in range(len(predicate_list))}
        pddl_elems = [e for e in pddl_snippet.split(' ') if e != '']
        idx = 0
        while idx < len(pddl_elems):
            if pddl_elems[idx] == '(' and idx + 1 < len(pddl_elems):
                if pddl_elems[idx + 1] in pred_names:
                    curr_pred_name = pddl_elems[idx + 1]
                    curr_pred_params = list()
                    target_pred_info = predicate_list[pred_names[curr_pred_name]]
                    # read params
                    idx += 2
                    while idx < len(pddl_elems) and pddl_elems[idx] != ')':
                        curr_pred_params.append(pddl_elems[idx])
                        idx += 1
                    # check if the num of params are correct
                    n_expected_param = len(target_pred_info['params'])
                    if n_expected_param != len(curr_pred_params):
                        if type_generalization == "return":
                            Logger.log(f"Predicate {curr_pred_name} at {idx} has {len(curr_pred_params)} parameters, but {n_expected_param} were expected. Can't generalize this", subsection=False)
                            continue # We ignore this number in regards to generalization. However, we can't generalize the action.
                        feedback_message = f'In the {part}, the predicate `{curr_pred_name}` requires {n_expected_param} parameters but {len(curr_pred_params)} parameters were provided. Please revise the PDDL model to fix this error.'
                        errors.append([False, 'invalid_predicate_usage', None, feedback_message])
                    # check if there is any unknown param
                    unknown = False
                    for curr_param in curr_pred_params:
                        if curr_param not in action_params:
                            if type_generalization == "return":
                                unknown = True
                                Logger.log(f"Unknown parameter {curr_param} at {idx} in predicate {curr_pred_name}. Can't generalize this", subsection=False)
                                continue
                            feedback_message = f'In the {part} and in the predicate `{curr_pred_name}`, there is an unknown parameter `{curr_param}`. You should define all parameters (i.e., name and type) under the `Parameters` list. Please revise the PDDL model to fix this error (and other potentially similar errors).'
                            errors.append([False, 'invalid_predicate_usage', None, feedback_message])
                    if unknown:
                        continue # We ignore this unknown parameter in regards to generalization. However, we can't generalize in this case.

                    # check if the object types are correct
                    target_param_types = [target_pred_info['params'][t_p] for t_p in target_pred_info['params']]
                    for param_idx, target_type in enumerate(target_param_types):
                        if param_idx >= len(curr_pred_params):
                            break # This should not happen, but we stop it if it does
                        curr_param = curr_pred_params[param_idx]
                        if curr_param not in action_params:
                            continue # We skip unknown parameters, though this should not happen

                        claimed_type = action_params[curr_param]

                        if not self._is_valid_type(target_type, claimed_type):
                            Logger.print(f"INVALID TYPE: '{claimed_type}' used instead of '{target_type}' for predicate `{curr_pred_name}` parameter `{curr_param}` in {part}")
                            match type_generalization:
                                # If we allow the predicate types to be generalized, the types can always be made to match, so a mismatch is not an error
                                case "allow":
                                    continue

                                # If we disallow the predicate types to be generalized,the types must match, so a mismatch is an immediate error
                                case "disallow":
                                    feedback_message = f'There is a syntax error in the {part.lower()}, the {param_idx+1}-{get_ordinal_suffix(param_idx+1)} parameter of `{curr_pred_name}` should be a `{target_type}` but a `{claimed_type}` was given. Please use the correct predicate or devise new one(s) if needed (but note that you should use existing predicates as much as possible).'
                                    errors.append([False, 'invalid_predicate_usage', None, feedback_message])
                                    continue

                                # If we want to return the types that need to be generalized, we will return a dict of the types that need to be generalized
                                case "return":
                                    if curr_pred_name not in preds_to_generalize:
                                        preds_to_generalize[curr_pred_name] = dict()
                                    # What is the current type of the parameter? (after any previous generalization)
                                    gen_pred_type = preds_to_generalize[curr_pred_name].get(param_idx, target_type)
                                    # If the current type is not a subtype of the target type, we need to generalize more
                                    if not self._is_valid_type(gen_pred_type, claimed_type):
                                        new_type = self.obj_hierarchy.shared_ancestor(claimed_type, gen_pred_type)
                                        if new_type is None:
                                            Logger.print("[WARNING]: Could not find a shared ancestor for the types", claimed_type, gen_pred_type, "likely the hierarchy is not rooted in 'object'.")
                                            new_type = "object"
                                        preds_to_generalize[curr_pred_name][param_idx] = new_type
            idx += 1

        if type_generalization == "return":
            return preds_to_generalize

        if len(errors) > 0:
            feedback_message = "\n".join([error[3] for error in errors])
            return False, 'invalid_predicate_usage', None, feedback_message

        return True, 'invalid_predicate_usage', None, None

    def check_predicate_usage(self, llm_output, generalize_predicate_types: Literal["allow", "dissallow", "return"] = "dissallow", **kwargs):
        """
        This function performs very basic check over whether the predicates are used in a valid way.
            This check should be performed at the end.

        If generalize_predicate_types is "return", the function will instead return a dict of which param types need to be generalized
        """
        errors = []

        # parse predicates
        new_predicates = parse_new_predicates(llm_output)
        curr_predicates = deepcopy(kwargs['curr_predicates'])
        new_filtered = [p for p in new_predicates if p['name'] not in [c['name'] for c in curr_predicates]]
        curr_predicates.extend(new_filtered)
        curr_predicates = parse_predicates(curr_predicates)

        # get action params
        params_info = parse_params(llm_output, include_internal=True)

        # check that headers exist
        if (not '\n### Action Preconditions' in llm_output) and (not '\n#### Action Preconditions' in llm_output):
            feedback_message = f'The header `### Action Preconditions` is missing in the PDDL model. Please include the header `### Action Preconditions` in the PDDL model.'
            errors.append([False, 'invalid_predicate_usage', None, feedback_message])
        else:
            header = '\n### Action Preconditions' if '\n### Action Preconditions' in llm_output else '\n#### Action Preconditions'
            if llm_output.split(header)[1].split("\n### ")[0].count('```') < 2:
                # no preconditions, probably.
                feedback_message = f'No PDDL expression was found in the "### Action Preconditions" heading. Please include the precondition within a markdown code block.'
                errors.append([False, 'invalid_predicate_usage', None, feedback_message])

        if (not '\n### Action Effects' in llm_output) and (not '\n#### Action Effects' in llm_output):
            feedback_message = f'The header `### Action Effects` is missing in the PDDL model. Please include the header `### Action Effects` in the PDDL model.'
            errors.append([False, 'invalid_predicate_usage', None, feedback_message])
        else:
            header = '\n### Action Effects' if '\n### Action Effects' in llm_output else '\n#### Action Effects'
            if llm_output.split(header)[1].split("\n### ")[0].count('```') < 2:
                # no effects, probably.
                feedback_message = f'No PDDL expression was found in the "### Action Effects" heading. Please include the effect within a markdown code block.'
                errors.append([False, 'invalid_predicate_usage', None, feedback_message])

        if len(errors) > 0:
            feedback_message = "\n".join([str(error[3]) for error in errors])
            return False, 'invalid_predicate_usage', None, feedback_message

        # check preconditions
        try:
            header = '\n### Action Preconditions' if '\n### Action Preconditions' in llm_output else '\n#### Action Preconditions'
            precond_str = llm_output.split(header)[1].split("\n###")[0].split('```')[1].strip()
            precond_str = precond_str.replace('\n', ' ').replace('(', ' ( ').replace(')', ' ) ')
            pre_result = self._check_predicate_usage_pddl(precond_str, curr_predicates, params_info, part='preconditions', type_generalization=generalize_predicate_types)

            # If we are not returning updated predicate types, we can return the validation info directly
            if not generalize_predicate_types == "return" and not pre_result[0]:
                errors.append(pre_result)
        except Exception as e:
            Logger.print(f"Error in checking preconditions: {e}")
            Logger.log(traceback.format_exc())
            feedback_message = f'Preconditions could not be correctly parsed and validated. Please ensure that the preconditions are correctly formatted and try again. The following error occurred: {e}'
            errors.append([False, 'invalid_predicate_usage', None, feedback_message])

        # check effects
        try:
            header = '\n### Action Effects' if '\n### Action Effects' in llm_output else '\n#### Action Effects'
            eff_str = llm_output.split(header)[1].split("\n###")[0].split('```')[1].strip()
            eff_str = eff_str.replace('\n', ' ').replace('(', ' ( ').replace(')', ' ) ')
            eff_result = self._check_predicate_usage_pddl(eff_str, curr_predicates, params_info, part='effects', type_generalization=generalize_predicate_types)

            # If we are not returning updated predicate types, we can return the validation info directly
            if not generalize_predicate_types == "return":
                errors.append(eff_result)
        except Exception as e:
            Logger.print(f"Error in checking effects: {e}")
            feedback_message = f'Effects could not be correctly parsed and validated. Please ensure that the effects are correctly formatted and try again.'
            errors.append([False, 'invalid_predicate_usage', None, feedback_message])

        if len(errors) > 0:
            feedback_message = "\n".join([str(error[3]) for error in errors])
            return False, 'invalid_predicate_usage', None, feedback_message

        # Merge the updated predicate types from preconditions and effects
        #name_result = self.check_predicate_names(llm_output, type_generalization="return", curr_predicates=curr_predicates)

        # Identify which predicates need to be generalized
        all_to_generalize = set(list(pre_result.keys()) + list(eff_result.keys())) # Deduplicated

        # Merge the generalizations from preconditions and effects
        to_generalize = pre_result
        for pred_name in all_to_generalize:
            Logger.print(f"Generalizing predicate {pred_name}")
            if pred_name not in eff_result:
                # If the predicate is not used in the effects, all arguments are already correctly generalized
                continue
            if pred_name not in to_generalize:
                # If the predicate is not used in the preconditions, we directly add the generalizations from the effects
                to_generalize[pred_name] = eff_result[pred_name]
                continue

            # If the predicate is used in both preconditions and effects, we need to merge the generalizations
            for param_idx in eff_result[pred_name].keys():
                if param_idx not in to_generalize[pred_name]:
                    # If the argument is changed in the effects but not in the preconditions, we need simply add the generalizations
                    to_generalize[pred_name][param_idx] = eff_result[pred_name][param_idx]
                else:
                    # If the predicate is changed in both preconditions and effects, we need to merge the generalizations
                    new_type = self.obj_hierarchy.shared_ancestor(
                        to_generalize[pred_name][param_idx], eff_result[pred_name][param_idx]
                    )
                    if new_type is None:
                        Logger.print("[WARNING]: Could not find a shared ancestor for the types", to_generalize[pred_name][param_idx], eff_result[pred_name][param_idx], "likely the hierarchy is not rooted in 'object'.")
                        new_type = "object"
                    to_generalize[pred_name][param_idx] = new_type

        return to_generalize