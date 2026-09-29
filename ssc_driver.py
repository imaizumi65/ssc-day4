import io
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

    def run(
        self,
        source: str | Path,
        target: str | Path | None = None,
        optimize: bool = True,
        execute: bool = False,
        force: bool = False,
        debug: bool = False,
    ) -> Path:
        source_path = (
            Path(source)
            if isinstance(source, (str, Path)) and Path(source).is_file()
            else None
        )

        if target:
            sso_path = Path(target)
        elif source_path:
            sso_path = source_path.with_suffix(".sso")
        else:
            sso_path = Path("output.sso")

        sso_text: str | None = None

        # 1. 既存の .sso を直接ロードする場合
        if source_path and source_path.suffix == ".sso":
            print(f"=== [Load SSO: {source_path.name}] ===")
            sso_text = source_path.read_text(encoding="utf-8")

        # 2. ビルド処理 (.ssl / .sss -> .sso)
        else:
            # タイムスタンプによるビルドスキップ判定
            if (
                source_path
                and not force
                and sso_path.is_file()
                and sso_path.stat().st_mtime >= source_path.stat().st_mtime
            ):
                print(f"[*] {sso_path.name} は最新です (ビルドスキップ)")
                sso_text = sso_path.read_text(encoding="utf-8")
            else:
                src_name = source_path.name if source_path else "StringSource"
                raw_code = (
                    source_path.read_text(encoding="utf-8")
                    if source_path
                    else str(source)
                )

                # Step 1: コンパイル
                if source_path and source_path.suffix == ".sss":
                    asm_code = raw_code
                else:
                    print(f"=== [Compile: {src_name}] ===")
                    asm_code = self.compiler.compile(raw_code)

                # Step 2: 最適化
                if optimize:
                    print(f"=== [Optimize -> {sso_path.name}] ===")
                    asm_code = self.optimizer.optimize(asm_code)
                else:
                    print(f"=== [Skip Optimize -> {sso_path.name}] ===")

                # Step 3: アセンブル (Word オブジェクト群の生成)
                words = self.assembler.assemble(asm_code)

                # Step 4: .sso テキスト出力のキャプチャ
                out_stream = io.StringIO()
                ssc_write(words, out_stream)
                sso_text = out_stream.getvalue()

                # ファイル書き出し
                sso_path.write_text(sso_text, encoding="utf-8")
                print(f"[*] 生成完了: {sso_path.name}")

        # 3. エミュレータ実行
        if execute:
            print(f"\n=== [Execute (debug={debug})] ===")
            emu = SSCEmulator(debug=debug)
            emu.load_program(io.StringIO(sso_text))
            emu.run()

        return sso_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="ssc_driver", description="SSC Integrated Build & Run Driver"
    )
    parser.add_argument("source", type=str, help="Input .ssl / .sss / .sso file")
    parser.add_argument("--no-opt", action="store_true", help="Disable optimizer")
    parser.add_argument("-x", "--execute", action="store_true", help="Execute in emulator")
    parser.add_argument("-f", "--force", action="store_true", help="Force rebuild")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    driver = SSCDriver()
    driver.run(
        source=args.source,
        optimize=not args.no_opt,
        execute=args.execute,
        force=args.force,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
