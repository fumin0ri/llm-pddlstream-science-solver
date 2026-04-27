from os import path

# Main directories
utils_dir = path.dirname(path.realpath(__file__))
nl2plan_dir = path.dirname(utils_dir)
root_dir = path.dirname(nl2plan_dir)
results_dir = path.join(root_dir, 'results')

# Prompts
prompt_dir = path.join(nl2plan_dir, 'prompts')
initial_facts_extraction_prompts = path.join(prompt_dir, '1_initial_facts_extraction')
stream_extraction_prompts = path.join(prompt_dir, '3_stream_extraction')
stream_construction_prompts = path.join(prompt_dir, '4_stream_construction')


# External tools
scorpion_dir = path.join(root_dir, 'scorpion')
val_dir = path.join(root_dir, "VAL", "build", "linux64", "release", "bin")
loki_dir = path.join(root_dir, 'Loki', "build", "exe")
downward_dir = path.join(root_dir, 'downward')
cpddl_path = path.join(root_dir, 'cpddl_latest.sif')