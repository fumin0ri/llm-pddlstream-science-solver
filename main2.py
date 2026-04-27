from NL2Plan.main import main as NL2Plan_main
from PDDL0.main import main as PDDL0_main
import argparse, os, json
from typing import Literal
import copy
# ★追加: Hugging Face datasetsをインポート
from datasets import load_dataset

root_dir = os.path.dirname(os.path.realpath(__file__))
domain_dir = os.path.join(root_dir, 'domains')
domains = os.listdir(domain_dir)

def main():
    # Subparser for each planner
    parser = argparse.ArgumentParser(description='Text to Plan.')
    subparsers = parser.add_subparsers(dest='planner', required=True, help="The planner to use. One of 'NL2Plan', 'PDDL0'")
    NL2Plan_parser = subparsers.add_parser("NL2Plan")
    PDDL0_parser = subparsers.add_parser("PDDL0")

    # Joint arguments for each planner
    for sub in [NL2Plan_parser, PDDL0_parser]:
        # 注意: desc.txtを読むためにdomain引数は依然として必要です（適切なフォルダを指定してください）
        sub.add_argument('--domain', default='logistics', type=str, help='The domain name.', choices=domains, nargs='?')
        sub.add_argument('--task', type=str, default='tasks', help='(Not used for HF dataset) The relative path to the task JSON file.')
        sub.add_argument('--llm', type=str, default='gpt-4o', help='The LLM engine name.', nargs='?')
        sub.add_argument('--instance_name', type=str, default=None, help='The base name of the subfolder where results are saved.')

    NL2Plan_parser.add_argument('--no_feedback', action='store_true')
    NL2Plan_parser.add_argument('--act_constr_iters', type=int, default=2)
    NL2Plan_parser.add_argument('--act_constr_feedback_level', type=str, choices=["domain", "action", "both"], default="domain", nargs='?')
    NL2Plan_parser.add_argument('--max_step_4_5_6_attempts', type=int, default=5)
    NL2Plan_parser.add_argument('--max_step_4_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--max_step_5_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--max_step_6_attempts', type=int, default=None)
    NL2Plan_parser.add_argument('--no_checkpoints', action='store_true')
    NL2Plan_parser.add_argument('--start_from', type=int, default=1, nargs='?')
    NL2Plan_parser.add_argument('--start_dir', type=str, default=None, nargs='?')
    NL2Plan_parser.add_argument('--end_after', type=int, default=6, nargs='?')
    PDDL0_parser.add_argument('--max_attempts', type=int, default=5)
    PDDL0_parser.add_argument('--disable_validation', action='store_true')

    args = parser.parse_args()

    # ドメインの説明文を読み込む (desc.txtが必要なため、既存のdomainフォルダを指定する必要があります)
    desc_path = os.path.join(root_dir, 'domains', args.domain, 'desc.txt')
    if os.path.exists(desc_path):
        with open(desc_path, 'r') as f:
            desc = f.read()
    else:
        print(f"Warning: {desc_path} not found. Running without domain description.")
        desc = ""
    
    # ★変更: ローカルJSONではなくHugging Faceからデータセットをロード
    hf_dataset_name = "SakanaAI/gsm8k-ja-test_250-1319"
    print(f"Loading dataset from Hugging Face: {hf_dataset_name}")
    
    ds = load_dataset(hf_dataset_name)
    
    # データセットのSplitを確認してリスト化 (通常は 'test' または 'train')
    if 'test' in ds:
        tasks = ds['test']
    elif 'train' in ds:
        tasks = ds['train']
    else:
        # splitがない場合は最初のキーを使用
        tasks = ds[list(ds.keys())[0]]

    tasks = list(tasks)
    print(f"Loaded {len(tasks)} tasks.")

    # ★変更: ループ処理 (全件処理に変更、start=16を削除)
    for i, task_item in enumerate(tasks[102:500],start=102):
        current_args = copy.deepcopy(args)
        
        # ★変更: HFデータセットの 'question' カラムを取得
        problem_text = task_item.get("question")
        
        # ★変更: GSM8Kには 'unit' がないため、空文字またはNoneとして扱う
        unit = task_item.get("unit", "") 

        if not problem_text:
            print(f"Skipping task {i+1} due to missing 'question'.")
            continue

        task_id = i + 1
        
        # ★変更: unitがある場合とない場合でプロンプトの構築を分ける
        if unit:
            current_args.desc_task = f'{desc}\n\n{problem_text} Please answer in the following units: {unit}'
        else:
            current_args.desc_task = f'{desc}\n\n{problem_text}'

        # インスタンス名の生成 (HF用に変更)
        base_instance_name = args.instance_name if args.instance_name else f"{args.domain}_gsm8k_ja_{args.llm}"
        current_args.instance_name = f"{base_instance_name}_task{task_id}"

        print(f"Running {current_args.planner} on domain {current_args.domain} with task ID {task_id} (GSM8K) and LLM {current_args.llm}.\n{'-'*50}")

        if current_args.planner == "NL2Plan":
            plan = NL2Plan_planner(current_args)
        elif current_args.planner == "PDDL0":
            plan = PDDL0_planner(current_args)
        else:
            raise ValueError("Invalid planner.")
        
        print(f"\nFinished task ID {task_id}.\n{'='*50}\n")

# 以下、Planner関数は変更なし
def NL2Plan_planner(args):
    feedback = None if args.no_feedback else "llm"
    max_4 = args.max_step_4_attempts if args.max_step_4_attempts is not None else args.max_step_4_5_6_attempts
    max_5 = args.max_step_5_attempts if args.max_step_5_attempts is not None else args.max_step_4_5_6_attempts
    max_6 = args.max_step_6_attempts if args.max_step_6_attempts is not None else args.max_step_4_5_6_attempts

    plan = NL2Plan_main(
        domain_name = args.domain,
        domain_task = args.desc_task,
        engine = args.llm,
        act_constr_iters = args.act_constr_iters,
        act_constr_feedback_level = args.act_constr_feedback_level,
        max_step_4_attempts = max_4,
        max_step_5_attempts = max_5,
        max_step_6_attempts = max_6,
        feedback = feedback,
        checkpoints = not args.no_checkpoints,
        start_from = args.start_from,
        start_dir = args.start_dir,
        end_after = args.end_after,
        instance_name = args.instance_name,
    )
    return plan

def PDDL0_planner(args):
    return PDDL0_main(
        domain = args.domain,
        domain_task_desc = args.desc_task,
        llm = args.llm,
        instance_name = args.instance_name,
        max_attempts = args.max_attempts,
        validation_enabled = not args.disable_validation
    )

if __name__ == "__main__":
    main()