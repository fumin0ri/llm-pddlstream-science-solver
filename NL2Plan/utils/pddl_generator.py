import os

from .logger import Logger
from .paths import results_dir
from .pddl_types import Action, Predicate, Stream

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
        self.stream_file = os.path.join(results_dir,experiment,"stream.pddl")
        self.run_file = os.path.join(results_dir,experiment,"run.py")

        # Initialize parts
        self.domain = domain
        self.predicates = ""
        self.actions = []
        self.streams = []
        self.objects = ""
        self.goal = ""
        self.overwritten_domain = None
        

    def add_action(self, action: Action):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding action.")
            return
        self.actions.append(action)
    
    def add_stream(self,stream: Stream):
        if not self.started:
            print("Warning: PDDLGenerator not started. Discarding stream.")
            return
        self.streams.append(stream)

    def reset_actions(self):
        self.actions = []

    def reset_streams(self):
        self.streams = []

    
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
    
    def set_init(self, init: Predicate):
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
        domain = self.generate_domain(self.domain, self.predicates, self.actions)
        streamp = self.generate_stream(self.domain, self.streams)
        streamc = self.generate_code(self.domain,self.streams,self.init)
        with open(self.domain_file, "w") as f:
            f.write(domain)
        with open(self.stream_file, "w") as f:
            f.write(streamp)
        with open(self.run_file, "w") as f:
            f.write(streamc)
        return domain,streamp,streamc

    def generate_domain(self, domain: str, predicates: str, actions: list[Action], allow_overwrite = True):        
        if self.overwritten_domain is not None and allow_overwrite:
            return self.overwritten_domain

        # Write domain file
        desc = ""
        desc += f"(define (domain {domain})\n"
        desc += self.indent(f"(:requirements\n   :strips :typing :equality :negative-preconditions :disjunctive-preconditions\n   :universal-preconditions :conditional-effects :existential-preconditions\n)", 1) + "\n\n"
        desc += f"   (:predicates \n{self.indent(predicates)}\n   )"
        desc += self.action_descs(actions)
        desc += "\n)"
        return desc
    
    def generate_stream(self, domain: str, streams: list[Stream]):        
       
        # Write stream file
        desc = ""
        desc += f"(define (stream {domain})\n"
        desc += self.stream_descs(streams)
        desc += "\n)"
        return desc

    def generate_code(self, domain: str, streams: list[Stream],init: Predicate):        
       
        # Write stream file
        desc = "import os\n"
        desc += "from pddlstream.language.constants import PDDLProblem\n"
        desc += "from pddlstream.algorithms.meta import solve\n\n"
        desc += """try:
    from pddlstream.language.generator import from_fn
    def s_fn(fn):
        def wrapper(*args):
            out = fn(*args)
            return out if isinstance(out, tuple) else (out,)
        return from_fn(wrapper)
except ImportError:
    from pddlstream.language.generator import from_gen_fn
    def s_fn(fn):
        def gen(*args):
            out = fn(*args)
            yield out if isinstance(out, tuple) else (out,)
        return from_gen_fn(gen)

# ======= python実装 =======================
        """

        desc += self.code_descs(streams) + "\n\n"
        desc += self.map_descs(streams)
        desc += self.init_desc(init)
    
        desc += "goal = ('done',)"
        desc += """\n
def read_text(filename):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

DOMAIN_PDDL  = read_text('domain.pddl')
STREAM_PDDL  = read_text('stream.pddl')\n\n"""

        desc += """if __name__ == "__main__":
    import json, time, traceback, sys
    from pathlib import Path

    t0 = time.time()
    error = None
    plan = None
    cost = None
    answers = []

    def iter_facts(evaluations):
        if not evaluations:
            return
        for group in evaluations:
            # group が [[pred,...],[pred,...],...] ならそれぞれを事実として返す
            if isinstance(group, (list, tuple)) and group and isinstance(group[0], (list, tuple)):
                for fact in group:
                    yield tuple(fact)
            else:
                # すでに1事実の形
                yield tuple(group)

    try:
        problem = PDDLProblem(
            DOMAIN_PDDL,
            constant_map={},
            stream_pddl=STREAM_PDDL,
            stream_map=stream_map,
            init=init,
            goal=goal
        )
        plan, cost, evaluations = solve(problem, unit_costs=True)
        print("Solution:", (plan, cost))

        # --- answer 述語を抽出（重複除去＆順序安定化のために set → list ソート） ---
        seen = set()
        flat = list(iter_facts(evaluations))
        for fact in flat:
            if not fact: 
                continue
            if fact[0] != 'answer':
                continue
            key = fact  # 重複検出用
            if key in seen:
                continue
            seen.add(key)
            # 引数部分を保存：1引数なら値だけ、複数ならリストに
            if len(fact) == 2:
                answers.append(fact[1])
            elif len(fact) > 2:
                answers.append(list(fact[1:]))
        # ----------------------------------------------------------------------

    except Exception as e:
        error = "".join(traceback.format_exception_only(type(e), e)).strip()

    dt = time.time() - t0

    result = {
        "task": Path(__file__).resolve().parent.name,
        "success": bool(plan),
        "cost": float(cost) if cost is not None else None,
        "time_sec": round(dt, 3),
        "plan": [str(a) for a in (plan or [])],
        "answer": answers,   # ← ここに answer の値一覧が入る
        "error": error,
    }

    out_path = Path(__file__).with_name("result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("RESULT_JSON:", json.dumps(result, ensure_ascii=False))
    sys.exit(0)
"""
    
        return desc



    def action_descs(self, actions = None) -> str:
        if actions is None:
            actions = self.actions
        desc = ""
        for action in actions:
            desc += "\n\n" + self.indent(self.action_desc(action),1)
        return desc

    def stream_descs(self, streams = None) -> str:
        if streams is None:
            streams = self.streams
        desc = ""
        for stream in streams:
            desc += "\n\n" + self.indent(self.stream_desc(stream),1)
        return desc


    def code_descs(self, streams = None) -> str:
        if streams is None:
            streams = self.streams
        desc = ""
        for stream in streams:
            desc += "\n\n" + self.code_desc(stream)
        return desc

    def map_descs(self, streams = None) -> str:
        if streams is None:
            streams = self.streams
        desc = "stream_map = {\n"
        for stream in streams:
            desc += "   "+self.map_desc(stream)
        desc += "}\n"
        return desc

    def indent(self, string: str, level: int = 2):
        return "   " * level + string.replace("\n", f"\n{'   ' * level}")
    
    def action_desc(self, action: Action):
        # parameters が None / リスト / イテラブルでも落ちないように正規化
        params = action.get('parameters') or {}
        if not isinstance(params, dict):
            try:
                params = dict(params)  # 例: [("?x","robot")] -> {"?x":"robot"}
            except Exception:
                params = {}

        # 空でも動くようにデフォルト
        pre = action.get('preconditions') or "()"
        eff = action.get('effects') or "()"
        name = action.get('name') or "anon_action"

        # ★ ここを params に変更。変数名も typ に
        param_str = "\n".join([f"{name} - {typ}" for name, typ in params.items()])

        desc  = f"(:action {name}\n"
        desc += f"   :parameters (\n{self.indent(param_str,2)}\n   )\n"
        desc += f"   :precondition\n{self.indent(pre,2)}\n"
        desc += f"   :effect\n{self.indent(eff,2)}\n"
        desc +=  ")"
        return desc

    def init_desc(self, init):
        """
        init: dict形式。init['init'] に複数行文字列が入っている想定。
        コメント（;以降）を削除し、整形して 'init = [ ... ]' 形式にする。
        """
        # init['init'] の中身を取得
        src = init.get('init', '')
        if not isinstance(src, str):
            src = str(src)

        lines = []
        for raw in src.splitlines():
            line = raw.strip()
            if not line:
                continue  # 空行スキップ

            # コメント削除（;以降）
            line = line.split(';', 1)[0].rstrip()

            # '(' が含まれている行だけ採用
            if '(' not in line:
                continue

            # カンマ付与（重複防止）
            if not line.endswith(','):
                line += ','

            lines.append(f"    {line}")

        # 出力整形
        desc = "init = [\n" + "\n".join(lines) + "\n]\n"
        return desc




    def stream_desc(self, stream: Stream):
        desc  = f"{stream['pddl']}\n"
        return desc

    def code_desc(self, stream: Stream):
        desc  = f"{stream['code']}\n"
        return desc
    
    def map_desc(self, stream: Stream):
        desc  = f"'{stream['name']}' : s_fn({stream['name']}_py),\n"
        return desc

    def get_domain(self):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before getting domain file.")
        if self.overwritten_domain is not None:
            return self.overwritten_domain
        self.generate()
        with open(self.domain_file, "r") as f:
            return f.read()
        
    
    def overwrite_domain(self, domain: str):
        if not self.started:
            raise ValueError("PDDLGenerator not started. Start PDDLGenerator before overwriting domain.")
        self.overwritten_domain = domain.lower()
    
    
    def single_action_domain(self, action: Action, predicates: list[Predicate]) -> str:
        predicate_str = "\n".join([pred["clean"].replace(":", " ; ",1) for pred in predicates])
        domain_str = self.generate_domain("SAD", self.types, predicate_str, [action])
        sad_file = os.path.join(os.path.dirname(self.domain_file), "sad.pddl")
        with open(sad_file, "w") as f:
            f.write(domain_str)
        return sad_file
    
PddlGenerator = PddlGeneratorClass()