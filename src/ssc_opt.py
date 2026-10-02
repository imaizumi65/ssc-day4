from dataclasses import dataclass, field
import sys
from ssc_core import AMAX, OPCODES


@dataclass
class Inst:
    """アセンブリ命令を表現する構造体 (IR: 中間表現)"""

    labels: list[str] = field(default_factory=list)
    op: str | None = None
    arg: str | None = None

    def to_asm(self) -> str:
        res = []
        for lbl in self.labels:
            res.append(f"{lbl}:")
        if self.op:
            if self.arg:
                res.append(f"\t{self.op}\t{self.arg}")
            else:
                res.append(f"\t{self.op}")
        return "\n".join(res)


@dataclass
class ProgramAnalysis:
    """プログラム全体の構造・制御フロー・データフロー解析結果"""

    label_to_index: dict[str, int] = field(default_factory=dict)
    min_backward_jump_index: int = 0
    is_self_modifying: bool = False
    first_write_index: dict[str, int] = field(default_factory=dict)
    inst_constant_values: dict[int, int] = field(default_factory=dict)


class SSCOptimizer:
    """SSCアセンブリ言語の高精度構造化オプティマイザ"""

    def optimize(self, asm_code: str) -> str:
        # 最適化の本体、各種最適化を順に適用

        # 1: アセンブリコードを解析・正規化して中間表現 (IR) に変換
        insts = self._parse_asm(asm_code)

        # ピープホール最適化を適用
        insts = self._peephole_optimize(insts)

        # ここに作成した各種最適化を適用する処理を記述してください。

        # 不要ラベルの削除と最終フォーマット
        insts = self._clean_labels(insts)

        return self._format_asm(insts)

    def _parse_asm(self, asm_code: str) -> list[Inst]:
        """入力アセンブリを構文解析し、小文字化・略称展開・シンボル化して IR に変換する"""
        # ssc_asm の OP_MAP に完全準拠した正規化テーブル
        mnemonic_map = {
            # OpCode 0: JUMP
            "j": "jump", "jmp": "jump", "jump": "jump", "jpc": "jump",
            # OpCode 1: ADD
            "a": "add", "add": "add", "plus": "add", "pls": "add",
            # OpCode 2: SUB
            "b": "sub", "sub": "sub", "minus": "sub",
            # OpCode 3: LOAD
            "l": "load", "load": "load", "ld": "load",
            # OpCode 4: STORE
            "t": "store", "store": "store", "sta": "store", "st": "store", "save": "store", "sto": "store",
            # OpCode 5: READ
            "r": "read", "read": "read", "rd": "read",
            # OpCode 6: WRITE
            "w": "write", "write": "write", "wr": "write",
            # OpCode 7: SHIFT
            "s": "shift", "shift": "shift",
            # 擬似命令 (データ定義): LIT
            "d": "lit", "data": "lit", "lit": "lit", "literal": "lit", "value": "lit",
            # 擬似命令 (領域確保): DECL
            "decl": "decl", "storage": "decl",
        }

        # 引数を必須とするオペコードの集合
        ops_requiring_arg = {
            "jump", "add", "sub", "load", "store",
            "read", "write", "shift", "lit", "decl",
        }

        insts: list[Inst] = []
        pending_labels: list[str] = []

        for line_idx, line in enumerate(asm_code.splitlines(), start=1):
            # 1. コメントの除去 (アセンブリ規格 ';' および '#' の双方に対応)
            if ";" in line:
                line = line.split(";", 1)[0]
            if "#" in line:
                line = line.split("#", 1)[0]

            line = line.strip()
            if not line:
                continue

            # 2. ラベルの切出し (例: "L_001: L/5")
            if ":" in line:
                parts = line.split(":", 1)
                pending_labels.append(parts[0].strip())
                rest = parts[1].strip()
            else:
                rest = line

            if rest:
                # 3. 簡易表記の区切り文字 '/' をスペースに置換 (例: "L/5" -> "L 5")
                rest = rest.replace("/", " ")
                tokens = rest.split(None, 1)

                op_raw = tokens[0].lower()

                # 未知のオペコードの場合は構文エラーを出力
                if op_raw not in mnemonic_map:
                    raise SyntaxError(
                        f"Assembly error at line {line_idx}: Unknown mnemonic '{tokens[0]}'"
                    )

                op = mnemonic_map[op_raw]
                arg = tokens[1] if len(tokens) > 1 else None

                # 不正アセンブリの即時検出 (引数不足チェック)
                if op in ops_requiring_arg and not arg:
                    raise SyntaxError(
                        f"Assembly error at line {line_idx}: '{op}' requires an operand"
                    )

                insts.append(Inst(labels=pending_labels, op=op, arg=arg))
                pending_labels = []

        if pending_labels:
            insts.append(Inst(labels=pending_labels))

        # 生の数値アドレス指定を標準ラベル (A_xxx) へ正規化変換
        return self._symbolize_raw_addresses(insts)

    def _symbolize_raw_addresses(self, insts: list[Inst]) -> list[Inst]:
        """生のアドレス参照 (例: load 5) を標準ラベル (A_005) に変換して正規化する"""
        address_referencing_ops = {
            "load",
            "store",
            "add",
            "sub",
            "write",
            "read",
            "jump",
        }
        auto_labels: dict[int, str] = {}

        for inst in insts:
            if not inst.op:
                continue

            # jump 0 (プログラム停止命令) はアドレスラベル化から除外
            if inst.op == "jump" and inst.arg == "0":
                continue

            # 数値アドレス指定の命令を検知して自動ラベル化
            if (
                inst.op in address_referencing_ops
                and inst.arg
                and inst.arg.isdigit()
            ):
                target_idx = int(inst.arg)
                if 0 <= target_idx < len(insts):
                    if target_idx not in auto_labels:
                        auto_labels[target_idx] = f"A_{target_idx:03d}"
                    inst.arg = auto_labels[target_idx]

        # 該当命令の行に生成したラベルを自動付与
        for target_idx, lbl_name in auto_labels.items():
            if lbl_name not in insts[target_idx].labels:
                insts[target_idx].labels.append(lbl_name)

        return insts

    def _analyze(self, insts: list[Inst]) -> ProgramAnalysis:
        analysis = ProgramAnalysis()
        # 後方ジャンプの初期値を命令列の長さ (範囲外のインデックス) に設定
        analysis.min_backward_jump_index = len(insts)

        for idx, inst in enumerate(insts):
            for lbl in inst.labels:
                analysis.label_to_index[lbl] = idx

        for idx, inst in enumerate(insts):
            if inst.op == "jump" and inst.arg in analysis.label_to_index:
                t_idx = analysis.label_to_index[inst.arg]
                if t_idx < idx:
                    analysis.min_backward_jump_index = min(
                        analysis.min_backward_jump_index, t_idx
                    )

        # 後方ジャンプが存在しなかった場合（初期値のままの場合）
        if analysis.min_backward_jump_index == len(insts):
            for idx, inst in enumerate(insts):
                if inst.op in ("decl", "lit") or (
                    inst.op == "jump" and inst.arg == "0"
                ):
                    analysis.min_backward_jump_index = idx
                    break

        instruction_labels = {
            lbl
            for lbl, idx in analysis.label_to_index.items()
            if idx >= analysis.min_backward_jump_index
            and (lbl.startswith("L_") or lbl.startswith("A_"))
        }
        for inst in insts:
            if inst.op == "store" and inst.arg in instruction_labels:
                analysis.is_self_modifying = True
                break

        for idx, inst in enumerate(insts):
            if inst.op in ("store", "read") and inst.arg:
                analysis.first_write_index.setdefault(inst.arg, idx)

        for idx, inst in enumerate(insts):
            if inst.op in ("jump", "lit") and inst.arg and inst.arg.isdigit():
                analysis.inst_constant_values[idx] = int(inst.arg)

        return analysis

    def _peephole_optimize(self, insts: list[Inst]) -> list[Inst]:
        """ピープホール（覗き穴）最適化を適用して冗長な命令列を削除・統合する"""
        # 命令列の並びを見て、冗長な命令を削除する
        raise NotImplementedError("SSCOptimizer._peephole_optimize() の最適化処理を実装してください。")
        optimized = insts.copy()

        return optimized


    def _clean_labels(self, insts: list[Inst]) -> list[Inst]:
        referenced_labels: set[str] = set()
        for inst in insts:
            if inst.arg and not inst.arg.isdigit():
                referenced_labels.add(inst.arg)

        for inst in insts:
            inst.labels = [
                lbl for lbl in inst.labels if lbl in referenced_labels
            ]

        return insts

    def _format_asm(self, insts: list[Inst]) -> str:
        lines = []
        for inst in insts:
            asm_str = inst.to_asm()
            if asm_str:
                lines.append(asm_str)
        return "\n".join(lines)


def main(
    args_list: list[str] | None = None,
    file: str | None = None,
    output: str | None = None,
    source_text: str | None = None,
):
    import argparse

    parser = argparse.ArgumentParser(
        prog="ssc_opt", description="SSC Optimizer (Peephole & Structure Optimizer)"
    )
    parser.add_argument(
        "file", nargs="?", type=str, default=None, help="Input assembly file (default: stdin)"
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None, help="Output assembly file (default: stdout)"
    )

    parsed_args = parser.parse_args(args_list)

    target_file = file if file is not None else parsed_args.file
    out_file = output if output is not None else parsed_args.output

    if source_text is None:
        if target_file:
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    source_text = f.read()
            except OSError as e:
                sys.stderr.write(f"ssc_opt: {e}\n")
                sys.exit(2)
        else:
            source_text = sys.stdin.read()

    optimizer = SSCOptimizer()
    try:
        opt_output = optimizer.optimize(source_text)
    except Exception as e:
        sys.stderr.write(f"ssc_opt error: {e}\n")
        sys.exit(1)

    if out_file:
        try:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(opt_output + ("\n" if not opt_output.endswith("\n") else ""))
        except OSError as e:
            sys.stderr.write(f"ssc_opt: {e}\n")
            sys.exit(2)
    else:
        sys.stdout.write(opt_output + ("\n" if not opt_output.endswith("\n") else ""))


SAMPLE_PROGRAM = """
	jump	L_001
L_001:
	read	V_x
	load	N_001
	store	V_f1
	load	N_001
	store	V_f2
L_002:
	load	V_x
	store	V__tmp
	load	N_000
	sub	V__tmp
	jump	L_003
	load	V_f1
	add	V_f2
	store	V_tmp
	load	V_f1
	store	V_f2
	load	V_tmp
	store	V_f1
	load	V_x
	sub	N_001
	store	V_x
	load	N_000
	jump	L_002
L_003:
	load	V_f2
	store	V__tmp
	write	V__tmp
	jump	0
N_001:
	lit	1
N_000:
	lit	0
V_x:
	decl	1
V_f1:
	decl	1
V_f2:
	decl	1
V_tmp:
	decl	1
V__tmp:
	decl	1
"""


if __name__ == "__main__":
    # --- 呼び出し方法の例 ---

    # 例1: ソースコード文字列を直接指定してテスト実行
    main(source_text=SAMPLE_PROGRAM)

    # 例2: ファイル名を直接指定してテスト実行
    # main(file="../samples/ssl/count.ssl")

    # 例3: コマンドライン引数（または標準入力）から実行する通常動作
    # main()
