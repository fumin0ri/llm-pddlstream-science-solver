from os import path

# Main directories
llmp_dir = path.dirname(path.realpath(__file__))
root_dir = path.dirname(llmp_dir)
results_dir = path.join(root_dir, 'pddl0-results')

# Prompts
prompt_dir = path.join(llmp_dir, 'prompts')