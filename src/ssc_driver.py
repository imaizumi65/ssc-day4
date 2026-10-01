import io
import sys
from pathlib import Path
from ssc_asm import SSCAssembler
from ssc_comp import SSLCompiler
from ssc_core import ssc_write
from ssc_emu import SSCEmulator
from ssc_opt import SSCOptimizer


class SSCDriver:
    """.sso (SSCオブジェクトファイル) の生成と実行を制御する統合ドライバ"""

    def __init__(self):
        self.compiler = SSLCompiler()
        self.optimizer = SSCOptimizer()
        self.assembler = SSCAssembler()

    def run_source(
        self,
        raw_code: str,
        source_ext: str = ".ssl",
        optimize: bool = True,
        execute: bool = False,
        debug: bool = False,
    ) -> str:
        """文字列ソースを受け取り、コンパイル・最適化・アセンブルを行うコア処理"""
        # Step 1: コンパイル (すでに .sss の場合はスキップ)
        if source_ext == ".sss":
            asm_code = raw_code
        else:
            asm_code = self.compiler.compile(raw_code)

        # Step 2: 最適化 (フラグに応じて適用)
        if optimize:
            asm_code = self.optimizer.optimize(asm_code)

        # Step 3: アセンブル (機械語 Word 列へ変換)
        words = self.assembler.assemble(asm_code)

        # Step 4: .sso 形式の文字列を出力生成
        out_stream = io.StringIO()
        ssc_write(words, out_stream)
        sso_text = out_stream.getvalue()

        # Step 5: エミュレータ実行指定がある場合
        if execute:
            emu = SSCEmulator(debug=debug)
            emu.load_program(io.StringIO(sso_text))
            emu.run()

        return sso_text


def main(
    args_list: list[str] | None = None,
    file: str | None = None,
    source_text: str | None = None,
    optimize: bool | None = None,
    execute: bool | None = None,
    force: bool | None = None,
    debug: bool | None = None,
):
    """ビルド＆実行ドライバのメイン関数

    PyCharm等からの直接呼び出し（デバッグ用）とCLIコマンド（パイプライン用）の
    両方に対応しています。
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="ssc_driver", description="SSC Integrated Build & Run Driver"
    )
    parser.add_argument(
        "file",
        nargs="?",
        type=str,
        default=None,
        help="Input file (.ssl / .sss / .sso). If omitted, reads from stdin.",
    )
    parser.add_argument(
        "--no-opt",
        action="store_true",
        help="Disable optimizer (default: optimization enabled)",
    )
    parser.add_argument(
        "-x",
        "--execute",
        action="store_true",
        help="Execute generated program in emulator",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force rebuild even if target is up-to-date",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug mode in emulator",
    )

    parsed_args = parser.parse_args(args_list)

    # パラメータの確定（関数の明示引数 > CLI引数）
    target_file = file if file is not None else parsed_args.file
    run_opt = optimize if optimize is not None else (not parsed_args.no_opt)
    run_exec = execute if execute is not None else parsed_args.execute
    run_force = force if force is not None else parsed_args.force
    run_debug = debug if debug is not None else parsed_args.debug

    driver = SSCDriver()

    # 1. ソースコードの入力決定（関数の直接文字列 > 指定ファイル > 標準入力）
    if source_text is not None:
        raw_code = source_text
        source_ext = ".ssl"
        source_path = None
    elif target_file:
        source_path = Path(target_file)
        if not source_path.is_file():
            sys.stderr.write(f"ssc_driver: file not found '{target_file}'\n")
            sys.exit(2)
        raw_code = source_path.read_text(encoding="utf-8")
        source_ext = source_path.suffix.lower()
    else:
        # 引数・ファイル指定なし：標準入力 (stdin) から読み込み
        source_path = None
        raw_code = sys.stdin.read()
        source_ext = ".ssl"

    # 2. .sso ファイルの直接実行処理
    if source_path and source_ext == ".sso":
        if run_exec:
            emu = SSCEmulator(debug=run_debug)
            emu.load_program(io.StringIO(raw_code))
            emu.run()
        else:
            print(raw_code, end="")
        return

    # 3. ファイル処理（.sso の生成）か、標準入出力処理かの分岐
    if source_path:
        sso_path = source_path.with_suffix(".sso")
        # タイムスタンプ判定 (force=True でなければ更新不要時スキップ)
        if (
            not run_force
            and sso_path.is_file()
            and sso_path.stat().st_mtime >= source_path.stat().st_mtime
        ):
            sso_text = sso_path.read_text(encoding="utf-8")
        else:
            sso_text = driver.run_source(
                raw_code,
                source_ext=source_ext,
                optimize=run_opt,
                execute=False,
                debug=run_debug,
            )
            sso_path.write_text(sso_text, encoding="utf-8")

        if run_exec:
            emu = SSCEmulator(debug=run_debug)
            emu.load_program(io.StringIO(sso_text))
            emu.run()
    else:
        # 標準入力からの場合：結果を標準出力にプリント（execute=True なら実行）
        sso_text = driver.run_source(
            raw_code,
            source_ext=source_ext,
            optimize=run_opt,
            execute=run_exec,
            debug=run_debug,
        )
        if not run_exec:
            print(sso_text, end="")


if __name__ == "__main__":
    # =========================================================================
    # 【PyCharm / IDE デバッグ時の使い方ガイド】
    #
    # スクリプトを直接「Run」または「Debug」する際は、以下の main() の引数を
    # 書き換えるだけで、環境変数を変更せずに様々なデバッグパターンをテストできます。
    # =========================================================================

    # --- パターン A [標準]: fib.ssl を対象に「最適化あり」でコンパイル＆実行 ---
    main(file="../samples/fib.ssl", optimize=True, execute=True, force=True)

    # --- パターン B [検証]: 最適化を「オフ」にして 32ワード制限エラーを確認 ---
    # main(file="../samples/fib.ssl", optimize=False, execute=True, force=True)

    # --- パターン C [デバッグ]: ステップ実行・レジスタダンプを有効化して実行 ---
    # main(file="../samples/fib.ssl", optimize=True, execute=True, force=True, debug=True)

    # --- パターン D [CLI]: CLI引数・標準入力処理の動作確認用（引数なしで呼び出し）---
    # main()
