import traceback

from .logger import Logger

def errors(file_path, display: bool = False) -> str | None:
    try:
        return errors_internal(file_path, display)
    except Exception as e:
        error_info = traceback.format_exc()
        Logger.print(f"Error in Paranthesis Parser:\n{error_info}")
        return None # In case the parsing fails somehow

def errors_internal(file_path, display: bool = False) -> str | None:
    # Sections that can appear in PDDL files
    major_sections = [':domain', ':constants', ':fluents', ':action', ':goal', ':init', ':objects', ':types', ':predicates', ':requirements']
    action_subsections = [':parameters', ':precondition', ':effect']
    previous_lines = []

    # Arguments at various levels
    token_at_depth = {}
    arguments_at_depth = {}
    keywords_supported_arguments = {
        "not": [1],
        "imply": [2],
        "forall": [2],
        "exists": [2],
        "and": range(0, 100), # Arbitrary limit
        "or": range(0, 100), # Arbitrary limit
        ":effect": [1],
        ":precondition": [1],
        ":goal": [1],
        ":init": range(0,10000), # Arbitrary limit
    }
    argument_depth_aborted = False

    # Invalid keywords for each subsection
    invalid_keywords = {
        ':precondition': [
            ('when ', "You can generally replace `when` with `imply` in the preconditions."),
            ('if ', "You can generally replace `if` with `imply` in the preconditions."),
            ("implies ",  "You can generally replace `implies` with `imply` in the preconditions."),
        ],
        ':effect': [
            ('imply ', "You can generally replace `imply` with `when` in the effects."),
            ('if ', "You can generally replace `if` with `when` in the effects."),
            ("implies ",  "You can generally replace `implies` with `when` in the effects."),
        ]
    }

    # Helper variables to track parsing state
    current_major_section = None
    current_subsection = None
    current_action_name = None
    parentheses_count = 0
    section_ended = False

    # Track errors
    errors = []

    # Remove initial and final parantheses
    text = open(file_path).read()
    text = text.split('(', 1)[1].rsplit(')', 1)[0]
    lines = text.split('\n')

    for line_num, line in enumerate(lines, start=1):
        previous_lines.append(line)
        line = line.split(';')[0]  # Remove comments

        if display:
            print(f"Line {line_num:3}: {line:40} | Parentheses Count: {parentheses_count:<3} | Section: {str(current_major_section) :<10}")

        # Check if the section has ended
        if parentheses_count == 0 and current_major_section and not section_ended:
            section_ended = True

            if major_sections == ":goal":
                if 0 in token_at_depth:
                    if arguments_at_depth[0] not in keywords_supported_arguments.get(token_at_depth[0], []):
                        errors.append(error_msg(
                            None, previous_lines,
                            f"Invalid number of arguments for '{token_at_depth[0]}' triggered at line {line_num} in {current_major_section}. Expected {keywords_supported_arguments.get(token_at_depth[0])} argument, but found {arguments_at_depth[0]} arguments. Likely, this is caused by a missing `imply`, `and`, `or`, or similar keyword previously. However, another possible cause is having too many closing parentheses. Explicitly consider which of these keywords you want to use.",
                        ))
                        #errors.append(f"Invalid number of arguments for '{token_at_depth[0]}' triggered at line {line_num}. Expected 1 argument, but found {arguments_at_depth[0]} arguments. The line which triggers the invalid number of arguments is: `{line}`. Likely, this is caused by a missing `imply`, `and`, `or`, or similar keyword previously. However, another possible cause is having too many closing parantheses. Explicitly consider which of these keywords you want to use.")

        section_name = f"{current_action_name}' subsection '{current_subsection}"  if current_action_name else current_major_section

        # Check for major sections (reset parenthesis count for each)
        for section in major_sections:
            if section in line:
                section_ended = False

                if parentheses_count != 0:
                    errors.append(error_msg(
                        None, previous_lines,
                        f"Unmatched parentheses in section '{section_name}' at some point before line {line_num}. There are {parentheses_count} unmatched opening parentheses. Likely, the correction is to add the missing closing parentheses to the end of the last `forall` or `exists` statement.",
                    ))
                    #errors.append(f"Unmatched parentheses in section '{section_name}' at some point before line {line_num}. There are {parentheses_count} unmatched opening parentheses. Likely, the correction is to add the missing closing parentheses to the end of the last `forall` or `exists` statement.")

                # Reset for new major section
                current_major_section = section
                parentheses_count = 0
                current_subsection = None
                argument_depth_aborted = False
                token_at_depth = {}
                arguments_at_depth = {}

                if section == ':action':
                    current_action_name = line.strip().split(' ')[1] if ' ' in line.strip() else "Action at line " + str(line_num)
                else:
                    current_action_name = None
                break

        # For :action, check for subsections like :effect, :precondition
        if current_major_section == ':action':
            for subsection in action_subsections:
                if subsection in line:
                    # Note that subsections should have +1 since they are nested within :action
                    if parentheses_count > 1:
                        errors.append(error_msg(
                            None, previous_lines,
                            f"Unmatched parentheses in action '{current_action_name}' subsection '{current_subsection}'. There are {parentheses_count-1} unmatched opening parentheses. Likely, the correction is to add the missing closing parentheses to the end of the last `forall` or `exists` statement.",
                        ))
                        #errors.append(f"Unmatched parentheses in action '{current_action_name}' subsection '{current_subsection}'. There are {parentheses_count-1} unmatched opening parentheses. Likely, the correction is to add the missing closing parentheses to the end of the last `forall` or `exists` statement.")
                    if parentheses_count < 1:
                        errors.append(error_msg(
                            None, previous_lines,
                            f"Unmatched parentheses in action '{current_action_name}' subsection '{current_subsection}'. There are {abs(parentheses_count-1)} unmatched closing parentheses. Likely, the correction is to add the missing opening parentheses to the beginning of the last `forall` or `exists` statement.",
                        ))
                        #errors.append(f"Unmatched parentheses in action '{current_action_name}' subsection '{current_subsection}'. There are {abs(parentheses_count-1)} unmatched closing parentheses. Likely, the correction is to add the missing opening parentheses to the beginning of the last `forall` or `exists` statement.")
                    if current_subsection in [':precondition', ':effect']:
                        if 2 in token_at_depth and arguments_at_depth[2] not in keywords_supported_arguments.get(token_at_depth[2]):
                            if arguments_at_depth[2] < min(keywords_supported_arguments[token_at_depth[2]]):
                                errors.append(error_msg(
                                    None, previous_lines,
                                    f"Too few arguments for '{token_at_depth[2]}' triggered at line {line_num} in {current_subsection} of {current_action_name}. Expected {keywords_supported_arguments.get(token_at_depth[2])} argument, but found {arguments_at_depth[2]} arguments. Likely, this is caused by a too early closing parenthesis.",
                                ))
                                #errors.append(f"Too few arguments for '{token_at_depth[2]}' triggered at line {line_num} in {current_subsection} of {current_action_name}. Expected {keywords_supported_arguments.get(token_at_depth[2])} argument, but found {arguments_at_depth[2]} arguments. The line which triggers the invalid number of arguments is: `{line.strip()}`. Likely, this is caused by a too early closing parenthesis.")
                            # If it was too many arguments, it would have been caught in the previous section. Frankly, the above will probably never trigger either. Only if the PDDL is really messed up.

                    # Reset for new subsection
                    current_subsection = subsection
                    parentheses_count = 1  # Reset for each subsection
                    argument_depth_aborted = False
                    token_at_depth = {}
                    arguments_at_depth = {}
                    break
            for keyword, sugg in invalid_keywords.get(current_subsection, []):
                if keyword in line:
                    errors.append(error_msg(
                        keyword.strip(), previous_lines,
                        f"Found invalid keyword '{keyword.strip()}' in action '{current_action_name}' subsection '{current_subsection}' at line {line_num}: `{line.strip()}`. {sugg}",
                    ))
                    #errors.append(f"Found invalid keyword '{keyword.strip()}' in action '{current_action_name}' subsection '{current_subsection}' at line {line_num}: `{line.strip()}`. {sugg}")

        # Construct section name for error messages
        section_name = f"{current_action_name}' subsection '{current_subsection}"  if current_action_name else current_major_section

        # For sections which can have expressions, i.e. :precondition, :effect and :goal, check for number of arguments
        if current_subsection in [':precondition', ':effect'] or current_major_section in [":goal", ":init"]:
            spaced_line = line.replace('(', ' ( ').replace(')', ' ) ')
            index = line.index(spaced_line.split()[0]) + 1 if len(spaced_line.split()) > 0 else 0 # This is used to keep track of the current index in the line
            detailed_parentheses_count = parentheses_count
            for keyword in spaced_line.split():
                index += len(keyword) + 1 # +1 to account for the space
                if display:
                    print(f"\tToken: {keyword :<6} | Temp Count: {detailed_parentheses_count :<3} | {argument_depth_aborted :<5} | {str(token_at_depth) :<20} | {str(arguments_at_depth) :<10}")
                if argument_depth_aborted:
                    break
                if keyword == '(':
                    detailed_parentheses_count += 1
                    continue
                if keyword == ')':
                    # If we've not seen any keyword, i.e. "()", then we need to safeguard
                    if not detailed_parentheses_count in arguments_at_depth:
                        arguments_at_depth[detailed_parentheses_count] = 0
                    if not detailed_parentheses_count in token_at_depth:
                        token_at_depth[detailed_parentheses_count] = None
                    # Before we leave, check if we have the right number of arguments
                    if arguments_at_depth[detailed_parentheses_count] < min(keywords_supported_arguments.get(token_at_depth[detailed_parentheses_count], range(0,100))):
                        expected_args = keywords_supported_arguments.get(token_at_depth[detailed_parentheses_count], range(0,100))
                        if len(expected_args) == 1:
                            expected_args = str(expected_args[0])
                        else:
                            expected_args = f"between {min(expected_args)} and {max(expected_args)}"
                        errors.append(error_msg(
                            index - int((len(keyword)+1)//2), previous_lines,
                            f"Too few arguments for '{token_at_depth[detailed_parentheses_count]}' triggered at line {line_num} in {section_name}. Expected {expected_args} arguments, but found {arguments_at_depth[detailed_parentheses_count]} arguments. Likely, this is caused by a too early closing parenthesis.",
                        ))
                        #errors.append(f"Too few arguments for '{token_at_depth[detailed_parentheses_count]}' triggered at line {line_num} in {section_name}. Expected {expected_args} arguments, but found {arguments_at_depth[detailed_parentheses_count]} arguments. The line which triggers the invalid number of arguments is: \n\t{line.strip()}\nLikely, this is caused by a too early closing parenthesis.")

                    # Let's leave the current depth
                    token_at_depth.pop(detailed_parentheses_count) # We left the current depth
                    detailed_parentheses_count -= 1
                    if detailed_parentheses_count < 1: # 1 means that the subsection is done, < 1 means that something is wrong with the parentheses, but that's handled elsewhere. Regardless, we can't keep going
                        argument_depth_aborted = True
                        continue

                    # Check if we're over the limit of the previous keyword
                    if not detailed_parentheses_count in token_at_depth:
                        arguments_at_depth[detailed_parentheses_count] = 0
                    arguments_at_depth[detailed_parentheses_count] += 1 # The thing we just left is an argument to the previous keyword
                    if arguments_at_depth[detailed_parentheses_count] > max(keywords_supported_arguments.get(token_at_depth[detailed_parentheses_count], range(0,100))): # Arbitrary limit, general predicates can have many arguments
                        expected_args = keywords_supported_arguments.get(token_at_depth[detailed_parentheses_count], range(0,100)) # Arbitrary limit, general predicates can have many arguments
                        if len(expected_args) == 1:
                            expected_args = str(expected_args[0])
                        else:
                            expected_args = f"between {min(expected_args)} and {max(expected_args)}"
                        errors.append(error_msg(
                            index - int((len(keyword)+1)//2), previous_lines,
                            f"Too many arguments for '{token_at_depth[detailed_parentheses_count]}' triggered at line {line_num} in {section_name}. Expected {expected_args} arguments, but found {arguments_at_depth[detailed_parentheses_count]} arguments. Likely, this is caused by a missing `imply`, `and`, `or`, or similar keyword previously though it could also be a missing closing parenthesis. Explicitly consider which of these keywords you want to use.",
                        ))
                        #errors.append(f"Too many arguments for '{token_at_depth[detailed_parentheses_count]}' triggered at line {line_num} in {section_name}. Expected {expected_args} arguments, but found {arguments_at_depth[detailed_parentheses_count]} arguments. The line which triggers the invalid number of arguments is: \n\t{line.strip()}\nLikely, this is caused by a missing `imply`, `and`, `or`, or similar keyword previously though it could also be a missing closing parenthesis. Explicitly consider which of these keywords you want to use.")
                    continue
                keyword = keyword.strip()
                if detailed_parentheses_count in token_at_depth and token_at_depth[detailed_parentheses_count] in keywords_supported_arguments:
                    # If something is already present at this depth, and it's a keyword (i.e. it's not a predicate), then we shouldn't try to add another top level argument
                    errors.append(error_msg(
                        index - int((len(keyword)+1)//2)-2, previous_lines,
                        f"It seems that the keyword '{keyword}' is not correctly nested at line {line_num} in {section_name}. It now appears to be a direct argument of '{token_at_depth[detailed_parentheses_count]}'. You should likely place '{keyword}' inside a set of parentheses.",
                    ))
                    #errors.append(f"It seems that the keyword '{keyword}' is not correctly nested at line {line_num} in {section_name}. It now appears to be a direct argument of '{token_at_depth[detailed_parentheses_count]}'. You should likely place '{keyword}' inside a set of parentheses. The line which triggers the invalid nesting is: \n\t{line.strip()}")
                else:
                    token_at_depth[detailed_parentheses_count] = keyword
                    arguments_at_depth[detailed_parentheses_count] = 0
            if display:
                print()

        # Count parentheses for the current section
        parentheses_count += line.count('(')
        parentheses_count -= line.count(')')

        # Check if we're seeing opening parenthesis without being in a section
        if section_ended and line.strip():
            if len(errors) >= 1 and errors[-1].startswith(f"Section '{section_name}' has ended by line"):
                start_line = errors[-1].split(" to ")[0].split(" ")[-1]
                errors[-1] = error_msg(
                    None, previous_lines,
                    f"Section '{section_name}' has ended by line {line_num}. The content at line {start_line} to {line_num} is therefore not connected to any section. This is likely caused by an unmatched closing parentheses, likely this is caused by a 'forall' or 'exist' statement having a closing parentheses too much or lacking an opening parentheses.",
                    max(4, line_num - int(start_line) + 2) # We include all the affected lines plus some margin, but at least 4
                )
                #errors[-1] = str(line_num).join(errors[-1].rsplit(previous_ending_line,1))
            else:
                errors.append(error_msg(
                    None, previous_lines,
                    f"Section '{section_name}' has ended by line {line_num}. The content at line {line_num} to {line_num} is therefore not connected to any section. This is likely caused by an unmatched closing parentheses, likely this is caused by a 'forall' or 'exist' statement having a closing parentheses too much or lacking an opening parentheses.",
                ))
                #errors.append(f"Section '{section_name}' has ended by line {line_num}. The content at line {line_num} to {line_num} is therefore not connected to any section. This is likely caused by an unmatched closing parentheses, likely this is caused by a 'forall' or 'exist' statement having a closing parantheses too much or lacking an opening parantheses.")

        # Detect excess closing parentheses within subsections
        if parentheses_count < 0:
            errors.append(error_msg(
                None, previous_lines,
                f"Too many closing parentheses in '{section_name}' leading to an error by line {line_num}. There are {abs(parentheses_count)} unmatched closing parentheses. Likely, the correction is to add the missing opening parentheses to the beginning of the last `forall` or `exists` statement.",
            ))
            #errors.append(f"Too many closing parentheses in '{section_name}' leading to an error by line {line_num}. There are {abs(parentheses_count)} unmatched closing parentheses. Likely, the correction is to add the missing opening parentheses to the beginning of the last `forall` or `exists` statement.")
            parentheses_count = 0  # Reset to prevent cascading errors

    # Check for any unmatched opening parentheses at the end of parsing
    if parentheses_count > 0:
        section_name = f"'{current_action_name}' subsection '{current_subsection}'"  if current_action_name else current_major_section
        errors.append(error_msg(
            None, previous_lines,
            f"Missing {parentheses_count} closing parentheses in '{section_name}' at the end of file. There are {parentheses_count} unmatched opening parentheses.",
        ))
        #errors.append(f"Missing {parentheses_count} closing parentheses in '{section_name}' at the end of file. There are {parentheses_count} unmatched opening parentheses.")

    if len(errors) >= 10:
        # Truncate the errors if there are too many
        errors = errors[:10] + ["Too many errors to display. Please fix the first errors and rerun the parser."]
    return "\n\n".join(errors) if errors else None

def error_msg(token: str | int | None, lines: list[str], msg: str, num_line_hist: int = 4) -> str:
    error = f"{msg}\n"
    error += highlight_error(lines, token, num_line_hist)
    return error

def highlight_error(lines: list[str], token: str | int | None, num_line_hist: int = 4) -> str:
    num_line_hist = min(num_line_hist, len(lines))
    line_num = len(lines) - num_line_hist - 1
    error = ""
    for error_line in range(line_num, len(lines)):
        error += f"\t{error_line+1:3} | {lines[error_line]}\n"
        if error_line == len(lines) - 1 and token is not None:
            if isinstance(token, str):
                token_index = lines[-1].find(token)
                if token_index != -1:
                    before_token = max(0, token_index - 1)
                    after_token = 4 if before_token == 0 else 0
                    error += "\t    |" + "_" * before_token + "^" + "_" * after_token + "\n"
            if isinstance(token, int):
                before_token = max(0, token - 1)
                after_token = 4 if before_token == 0 else 0
                error += "\t    |" + "_" * before_token + "^" + "_" * after_token + "\n"
    return error