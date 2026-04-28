# LLM-PDDLStream Science Solver

このリポジトリは、自然言語で書かれた大学レベルの科学問題を、大規模言語モデルを用いて実行可能な `PDDLStream` プログラムへ変換し、解答することを目指した私の卒業研究の実装です。

本システムは、LLM に最終的な数値解答を一度で出させるのではなく、問題解決を次のような記号的な中間段階へ分解します。

1. 問題文から与えられた事実を抽出する
2. stream レベルの解法手順を生成する
3. 実行可能な `PDDLStream` 成果物（`domain.pddl`, `stream.pddl`, `run.py`）を構成する

生成されたプログラムはそのまま実行され、SciBench の正解と自動で照合されます。

## この研究の目的

大規模言語モデルは流暢な説明を生成できますが、数値計算を伴う推論は依然として不安定なことがあります。そこで卒論では、推論過程を明示的な計算ステップとして外化し、それを `PDDLStream` で実行させることで、より頑健な解法にできないかを検証しました。

このプロジェクトは [NL2Plan](https://github.com/mrlab-ai/NL2Plan) をベースとした派生実装ですが、目的は古典的な行動計画ではなく、科学問題の解法生成です。主な貢献は、テキストから PDDL を作るだけでなく、実行可能な stream 定義と Python 計算コードまで一貫して生成するパイプラインへ拡張した点にあります。

## システム概要

![System overview](docs/system_overview.png)

パイプラインは、各段階に LLM feedback ループを持つ 3 つのステップで構成されています。

- `Initial Facts Extraction`
  問題に含まれる物理量や条件を抽出し、初期事実へ変換します。
- `Stream Extraction`
  解法を段階的な stream 群として表現し、式・必要な入力・生成される事実を定義します。
- `Stream Construction`
  各 stream を `PDDLStream` の宣言的表現と、それに対応する Python コードへ変換します。

生成された成果物は `PDDLStream` によって実行され、最終的な数値解答は `result.json` から取得されます。

## このリポジトリでできること

SciBench の問題に対して、このリポジトリは次の処理を行えます。

- 問題文と要求単位を読み込む
- 直接解答ではなく、構造化された中間推論を生成する
- `domain.pddl`, `stream.pddl`, `run.py` を合成する
- 生成した解法を `PDDLStream` で実行する
- 予測した数値解答を SciBench の正解と比較する

この構成により、最終解答だけでなく、抽出された事実、生成された stream、生成コード、実行ログまで追跡できます。各タスクの結果ディレクトリを開けば、推論の全過程を確認できます。

## 中核アイデア

この研究の中心にある設計思想は、科学問題の解法を「構造化された推論のためのプログラム合成」として扱うことです。

単一の Chain-of-Thought に依存する代わりに、このシステムは LLM に対して次のことを要求します。

- 与えられている量を特定する
- どの中間量を計算する必要があるかを決める
- 各計算を stream として命名する
- stream の入力と出力を記号的に表現する
- 実際に計算を行う Python コードを生成する

この設計は、明示的な分解の方が、直接解答生成よりも推論を透明化し、検証しやすくできるのではないかという仮説に基づいています。

## 評価概要

卒論では `gpt-oss-20b` を用いて SciBench で評価し、直接的な Chain-of-Thought prompting と比較しました。

### SciBench における正答率

| Method | atkins | chemmc | quan | matter | fund | class | thermo | diff | stat | calc | Average |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CoT | 71.4 | 81.6 | 66.7 | 68.1 | 88.7 | 64.3 | 72.7 | 76.0 | 80.6 | 90.5 | **77.06** |
| Ours | 64.8 | **89.5** | **72.7** | 66.0 | 77.5 | 57.1 | 63.6 | 76.0 | 80.6 | 90.5 | **73.83** |

卒論での主な観察は次の通りです。

- 提案手法は全体平均では直接 CoT を上回りませんでした。
- 一方で、`chemmc` と `quan` では性能が向上しました。
- `diff`, `stat`, `calc` では CoT と同等の結果でした。
- 最も大きな性能低下は、実行段階以前に、Stream Extraction で生成される中間解法そのものが不安定になる科目で見られました。

### PDDL 生成エラー率

| Metric | atkins | chemmc | quan | matter | fund | class | thermo | diff | stat | calc | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Total Problems | 105 | 38 | 33 | 47 | 71 | 56 | 66 | 50 | 72 | 42 | 580 |
| Error Count | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 2 | 7 | 1 | 12 |
| Error Rate (%) | 0.0 | 0.0 | 0.0 | 2.1 | 0.0 | 0.0 | 1.5 | 4.0 | 9.7 | 2.4 | **2.1** |

これは卒論の中でも重要な結果でした。エンドツーエンドの正答率は CoT に及ばなかった一方で、PDDL 生成パイプライン自体は比較的安定しており、`580` 問中の成果物生成エラー率は `2.1%` にとどまりました。

## リポジトリ構成

- `main.py`
  SciBench 実行と評価のためのエントリポイントです。
- `pddlstream_eval.py`
  生成された `run.py` を実行し、数値解答を採点します。
- `science_solver/`
  3 段階の生成パイプライン本体です。
- `science_solver/pipeline.py`
  全体のワークフローを制御します。
- `science_solver/extract_initial_facts.py`
  Step 1 として predicate と初期事実を抽出します。
- `science_solver/extract_streams.py`
  Step 2 として stream 単位の解法手順を生成します。
- `science_solver/build_streams.py`
  Step 3 として `PDDLStream` 定義と Python コードを合成します。
- `domains/scibench/`
  データセットの説明と task JSON が含まれます。
- `external/pddlstream/`
  `PDDLStream` の Git submodule です。
- `scripts/setup_pddlstream.py`
  submodule 初期化と `Fast Downward` 準備用のセットアップスクリプトです。

## セットアップ

submodule を含めて clone します。

```bash
git clone --recursive https://github.com/fumin0ri/llm-pddlstream-science-solver.git
cd llm-pddlstream-science-solver
```

すでに submodule なしで clone 済みの場合は、次を実行してください。

```bash
git submodule update --init --recursive
```

続いて `PDDLStream` と `Fast Downward` をセットアップします。

```bash
python scripts/setup_pddlstream.py
```

このスクリプトは `external/pddlstream` submodule の初期化、nested submodule の更新、`Fast Downward` の build を行います。新しい `CMake` 環境でも動くよう、フォールバック処理も入っています。

## 実行方法

実行例:

```bash
python main.py --domain scibench --task dataset/original/atkins --llm gpt-oss:latest
```

主なオプション:

- `--instance_name`
  出力ディレクトリ名の接頭辞を上書きします。
- `--no_feedback`
  LLM feedback ループを無効化します。
- `--act_constr_iters`
  Stream Construction 中の feedback 改善回数を指定します。
- `--act_constr_feedback_level`
  `domain`, `stream`, `both` から選択します。
- `--max_step_4_attempts`
  stream ごとの最大再試行回数です。
- `--skip_pddlstream_eval`
  `PDDLStream` 実行と採点を行わず、成果物生成のみを行います。
- `--pddlstream_dir`
  ローカルの `PDDLStream` チェックアウト先を上書きします。

## 出力

各タスクの結果は次のディレクトリ配下に保存されます。

```text
results/scibench/<instance_name>/
```

主な出力ファイル:

- `domain.pddl`
- `stream.pddl`
- `run.py`
- `result.json`
- `evaluation.json`
- `pddlstream_stdout.log`
- `pddlstream_stderr.log`
- `1_Init_Facts_Extraction.log`, `3_Stream_Extraction.log`, `4_Stream_Construction.log` などの各段階ログ

`evaluation.json` には次の情報が保存されます。

- 予測した数値解答
- SciBench の正解
- 正誤判定
- 実行ログ
- 実行時エラーメッセージ

現在の採点では、相対誤差 `0.5%` 以内であれば正解と判定し、ゼロ付近の値のために小さな絶対誤差許容も加えています。

## 評価出力例

```json
{
  "predicted_answer": 50.68,
  "expected_answer": 50.7,
  "correct": true
}
```

## この研究で得た学び

このプロジェクトを通して、自然言語による推論と実行可能な推論の間には大きな隔たりがあることを強く実感しました。

- LLM は妥当な解法を文章として説明できても、それを安定した記号的成果物へ変換するには慎重な prompt 設計と反復的な検証が必要でした。
- 最も壊れやすい部分は必ずしも PDDL の構文ではなく、Stream Extraction における高レベルな解法分解そのものが少しずれるケースでした。
- 生の正答率で CoT に勝てない場合でも、実行可能な中間表現には価値があります。理由は、推論過程を観察・検証・デバッグできるからです。

## 限界

- 現時点では平均正答率は直接 CoT を下回っています。
- 性能は Step 2 の stream レベル解法生成の質に強く依存します。
- 実装はこのリポジトリ内の SciBench ワークフロー向けに特化しており、汎用的な定理証明器や万能な科学問題ソルバではありません。


