from dataclasses import dataclass, field
import io
import sys
from pathlib import Path

from ssc_core import AMAX, OPCODES

# from ssc_opt import * 実行時の名前空間汚染を防止
__all__ = ["SSCOptimizer", "Inst", "ProgramAnalysis"]


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
    """プログラム全体の構造解析結果"""

    label_to_index: dict[str, int] = field(default_factory=dict)
    min_backward_jump_index: int = 99999
    is_self_modifying: bool = False
    first_write_index: dict[str, int] = field(default_factory=dict)
    inst_constant_values: dict[int, int] = field(default_factory=dict)


class SSCOptimizer:
    """【第4回 課題】SSCアセンブリ言語のコードオプティマイザ"""

    def optimize(self, asm_code: str) -> str:
        """アセンブリコードを受け取り、最適化されたアセンブリコードを返す"""
        insts = self._parse_asm(asm_code)

        # 1. 覗き穴最適化 (Peephole Optimization)
        insts = self._peephole_optimize(insts)

        # 2. プログラム構造解析
        analysis = self._analyze(insts)

        # 3. エントリポイントの最適化 (不要な初期ジャンプの除去)
        insts = self._optimize_entry_point(insts, analysis)

        # 4. 定数共有 (Constant Sharing)
        analysis = self._analyze(insts)
        insts = self._optimize_constants_general(insts, analysis)

        # 5. メモリオーバーレイ (Memory Overlay)
        analysis = self._analyze(insts)
        insts = self._optimize_memory_overlay_general(insts, analysis)

        # 6. 未参照ラベルのクリーンアップとフォーマット出力
        insts = self._clean_labels(insts)
        return self._format_asm(insts)

    def _parse_asm(self, asm_code: str) -> list[Inst]:
        """アセンブリ文字列を IR (Inst オブジェクトのリスト) に変換 (提供コード)"""
        insts: list[Inst] = []
        pending_labels: list[str] = []

        for line in asm_code.splitlines():
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            if ":" in line:
                parts = line.split(":", 1)
                pending_labels.append(parts[0].strip())
                rest = parts[1].strip()
            else:
                rest = line

            if rest:
                tokens = rest.split(None, 1)
                op = tokens[0]
                arg = tokens[1] if len(tokens) > 1 else None
                insts.append(Inst(labels=pending_labels, op=op, arg=arg))
                pending_labels = []

        if pending_labels:
            insts.append(Inst(labels=pending_labels))

        return insts

    def _analyze(self, insts: list[Inst]) -> ProgramAnalysis:
        """制御フローと変数の使用状況を解析 (提供コード)"""
        analysis = ProgramAnalysis()

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

        if analysis.min_backward_jump_index == 99999:
            for idx, inst in enumerate(insts):
                if inst.op in ("decl", "lit") or (
                    inst.op == "jump" and inst.arg == "0"
                ):
                    analysis.min_backward_jump_index = idx
                    break

        for idx, inst in enumerate(insts):
            if inst.op in ("store", "read") and inst.arg:
                analysis.first_write_index.setdefault(inst.arg, idx)

        return analysis

    # -----------------------------------------------------------------
    # 【課題1】覗き穴最適化 (Peephole Optimization)
    # -----------------------------------------------------------------
    def _peephole_optimize(self, insts: list[Inst]) -> list[Inst]:
        """局所的な冗長パターンの除去

        - 連続する不必要な load / store の削除 (例: store V_tmp 後に直ちに行われる load V_tmp)
        - 冗長なロード処理のスキップ
        """
        optimized: list[Inst] = []
        i = 0
        ac_set: set[str] = set()

        while i < len(insts):
            curr = insts[i]

            if curr.labels:
                ac_set.clear()

            # TODO [課題1]:
            # 1. curr.op == "load" のとき、すでに AC にその引数 (curr.arg) が保持されている場合は
            #    この load 命令をスキップ (除去) せよ。
            # 2. load -> store V__tmp -> write V__tmp のパターンを検出した場合、
            #    直ちに write 命令 1 行に短縮・削除するルールを実装せよ。

            ac_set.clear()
            optimized.append(curr)
            i += 1

        return optimized

    # -----------------------------------------------------------------
    # 【課題2】定数共有 (Constant Sharing)
    # -----------------------------------------------------------------
    def _optimize_constants_general(
        self, insts: list[Inst], analysis: ProgramAnalysis
    ) -> list[Inst]:
        """重複する定数 (lit 命令) の一元化

        - N_001: lit 1 などの重複する宣言を集約し、命令側の参照ラベルを共通化せよ。
        """
        # TODO [課題2]:
        # 重複する lit 命令の値を検出し、1つのメモリセルを複数の参照元で共有するロジックを完成させよ。
        return insts

    # -----------------------------------------------------------------
    # 【課題3】メモリオーバーレイ (Memory Overlay)
    # -----------------------------------------------------------------
    def _optimize_memory_overlay_general(
        self, insts: list[Inst], analysis: ProgramAnalysis
    ) -> list[Inst]:
        """変数領域 (decl) の再利用・オーバーレイ配置

        - プログラム前半で一度も実行・更新されない変数領域 (decl) を、
          非再実行領域や中間領域へ重ね合わせてコード長を圧縮せよ。
        """
        # TODO [課題3]:
        # decl 命令で確保されている変数領域を、プログラム内の非再実行領域のアドレスへ統合・配置せよ。
        return insts

    def _optimize_entry_point(
        self, insts: list[Inst], analysis: ProgramAnalysis
    ) -> list[Inst]:
        """先頭の不要な jump L_001 を除去 (提供コード)"""
        if len(insts) < 2 or insts[0].op != "jump" or not insts[0].arg:
            return insts

        entry_label = insts[0].arg
        if entry_label not in insts[1].labels:
            return insts

        is_referenced = any(
            inst.arg == entry_label for inst in insts[2:] if inst.op
        )
        if not is_referenced:
            insts[1].labels.remove(entry_label)
            insts = insts[1:]

        return insts

    def _clean_labels(self, insts: list[Inst]) -> list[Inst]:
        """どこからも参照されていないラベルを削除 (提供コード)"""
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
    source_text: str | None = None,
):
    """オプティマイザのメイン関数

    CLIコマンド、パイプライン（標準入力）、PyCharm等からの直接呼び出しの
    全てに対応しています。
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ssc_opt", description="SSC Optimizer (Peephole & Structure Optimizer)"
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=str,
        default=None,
        help="Input .sss file (default: stdin)",
    )

    parsed_args = parser.parse_args(args_list)
    target_file = file if file is not None else parsed_args.file

    # 入力ソースの確定処理 (明示文字列 > 指定ファイル > 標準入力)
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
        print(opt_output)
    except Exception as e:
        sys.stderr.write(f"ssc_opt error: {e}\n")
        sys.exit(1)


# デフォルトのセルフテスト用サンプルプログラム
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
    # =========================================================================
    # 【PyCharm / IDE デバッグ時の使い方ガイド】
    #
    # IDE（PyCharm等）からこのファイルを直接「Run / Debug」する場合、
    # カレントディレクトリは src/ になるため、samples/ へのパスには `../` を付けます。
    # =========================================================================

    # --- パターン A [基本テスト]: 組込サンプルプログラムを渡して最適化 ---
    main(source_text=SAMPLE_PROGRAM)

    # --- パターン B [ファイル指定]: 指定した .sss ファイルをロードして最適化 ---
    # main(file="../samples/loop.sss")

    # --- パターン C [標準入力]: CLIのパイプラインや手動入力をテスト（引数なし） ---
    # main()
