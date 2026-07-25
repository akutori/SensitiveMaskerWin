from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from masking_core.masker import MappingStore, apply_profile
from masking_core.models import RuleProfile
from masking_core.profile_io import ProfileLoadError, load_profile

# ネストされたインラインフラググループ ((?s:...), (?is:...) 等) の検出用。
# Pythonはグローバルなインラインフラグ((?s)等)しかcompiled.flagsに反映しない
# ため、スコープ付きの場合は正規表現の文字列自体を見るしかない。
_SCOPED_DOTALL_RE = re.compile(r"\(\?[a-zA-Z]*s[a-zA-Z]*:")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.main",
        description="ルールプロファイルを使ってテキスト中の機微情報をマスキングします。",
    )
    parser.add_argument("--profile", required=True, help="RuleProfile JSONファイルのパス")
    parser.add_argument("--encoding", default="utf-8", help="ファイル読み書き時の文字エンコーディング")
    parser.add_argument(
        "--reset-mapping-per-file",
        action="store_true",
        help="バッチモード専用: MappingStoreをファイル間で共有せず、ファイルごとにリセットする",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--input", help="入力ファイルパス(省略時は標準入力)")
    mode_group.add_argument(
        "--batch", nargs="+", metavar="INPUT", help="複数の入力ファイルをバッチ処理する"
    )

    parser.add_argument("--output", help="出力ファイルパス(省略時は標準出力。--batch使用時は無視される)")
    parser.add_argument("--output-dir", help="--batch使用時の出力先ディレクトリ(--batch使用時は必須)")
    parser.add_argument(
        "--stream",
        action="store_true",
        help=(
            "標準入力を1行ずつ読み取り、都度マスクして即座に標準出力へ書き込みます"
            "(パイプ経由の長時間実行プロセスに有用)。--input/--output/--batch/"
            "--reset-mapping-per-fileとは併用できません。複数行にまたがる正規表現ルールは"
            "1行ずつの処理のため正しく機能しない場合があります(よくあるケースは警告を"
            "表示しますが、検知できない場合もあります)。'^'/'$'で行頭/行末を指定する"
            "ルールも、通常モード(文書全体が対象)とは挙動が異なる場合がある点に"
            "注意してください。"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Must run before any stderr write, including parser.error() below and
    # the ProfileLoadError path further down: a real stderr TextIOWrapper
    # defaults to the console's codepage, which mangles when stderr is
    # redirected/piped instead of shown on that console -- same class of bug
    # _reconfigure_encoding already fixes for stdin/stdout. Hardcoded to
    # utf-8 rather than args.encoding: --encoding governs the data being
    # masked (which a user may legitimately set to something narrow like
    # ascii), not this CLI's own Japanese diagnostic text, which must always
    # be encodable regardless of that choice.
    _reconfigure_encoding(sys.stderr, "utf-8")

    # --streamの併用不可チェックは--batch自身のチェックより先に行う。
    # 後回しにすると、例えば `--stream --batch a.log`(--output-dir省略)は
    # 先に「--output-dirが必須」という--batch側のエラーで止まってしまい、
    # そもそも--streamとの組み合わせ自体が不可能であることが2回目の実行まで
    # 分からない。
    if args.stream:
        if args.batch:
            parser.error("--stream は --batch と併用できません")
        if args.input:
            parser.error("--stream は --input と併用できません(標準入力のみ対応)")
        if args.output:
            parser.error("--stream は --output と併用できません(標準出力のみ対応)")
        if args.output_dir:
            parser.error("--stream は --output-dir と併用できません")
        if args.reset_mapping_per_file:
            parser.error("--stream は --reset-mapping-per-file と併用できません(バッチモード専用のオプションです)")

    if args.batch:
        if not args.output_dir:
            parser.error("--batch使用時は --output-dir が必須です")
        if args.output:
            parser.error("--output は --batch と併用できません")
    elif args.output_dir:
        parser.error("--output-dir は --batch と併用してください")

    try:
        profile = load_profile(args.profile)
    except ProfileLoadError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.batch:
        return _run_batch(args, profile)
    if args.stream:
        return _run_streaming(args, profile)
    return _run_single(args, profile)


def _reconfigure_encoding(stream, encoding: str) -> None:
    # Real stdin/stdout are TextIOWrapper and default to the console's
    # codepage, which may not match the bytes actually being piped in
    # (e.g. PowerShell sending UTF-8). Test doubles like io.StringIO have
    # no encoding concept at all, so skip them via the hasattr guard.
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding=encoding)


def _read_input_file(path: Path, encoding: str) -> str | None:
    """Reads path as text, or prints a clean error and returns None on failure.

    Covers both missing/unreadable files (OSError) and files whose bytes
    don't match `encoding` (UnicodeDecodeError) -- either would otherwise
    surface as a raw, unhandled traceback.
    """
    try:
        return path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        print(
            f"入力ファイル '{path}' を読み込めません(ファイルが存在するか、"
            f"文字エンコーディングが --encoding='{encoding}' と一致しているか"
            f"確認してください): {exc}",
            file=sys.stderr,
        )
        return None


def _write_output_file(path: Path, text: str, encoding: str) -> bool:
    """Writes text to path; returns False after printing a clean error on failure."""
    try:
        path.write_text(text, encoding=encoding)
        return True
    except (OSError, UnicodeEncodeError) as exc:
        print(
            f"出力ファイル '{path}' に書き込めません(--encoding='{encoding}' "
            f"を確認してください): {exc}",
            file=sys.stderr,
        )
        return False


def _run_single(args: argparse.Namespace, profile) -> int:
    store = MappingStore()

    if args.input:
        text = _read_input_file(Path(args.input), args.encoding)
        if text is None:
            return 1
    else:
        _reconfigure_encoding(sys.stdin, args.encoding)
        try:
            text = sys.stdin.read()
        except UnicodeDecodeError as exc:
            print(
                f"標準入力の読み込みに失敗しました(文字エンコーディングが "
                f"--encoding='{args.encoding}' と一致しているか確認してください): {exc}",
                file=sys.stderr,
            )
            return 1

    masked, _ = apply_profile(text, profile, store)

    if args.output:
        if not _write_output_file(Path(args.output), masked, args.encoding):
            return 1
    else:
        _reconfigure_encoding(sys.stdout, args.encoding)
        try:
            sys.stdout.write(masked)
        except UnicodeEncodeError as exc:
            print(
                f"標準出力への書き込みに失敗しました(--encoding='{args.encoding}' "
                f"を確認してください): {exc}",
                file=sys.stderr,
            )
            return 1

    return 0


def _warn_about_multiline_rules(profile: RuleProfile) -> None:
    """Warns to stderr about enabled regex rules that look like they intend
    to match across multiple lines -- --stream processes one line at a
    time, so such a rule would silently stop matching. Rule's own
    model_validator already guarantees any pattern_type="regex" pattern
    compiles, so re.compile() here cannot raise.

    Checks (any one triggers the warning):
    - a raw newline character embedded in the pattern
    - the \\n regex escape token (backslash + "n") -- the realistic,
      idiomatic way to author a newline-spanning pattern in a JSON profile,
      and the ONLY way reachable via the GUI at all (its pattern field is a
      single-line Entry that cannot receive a literally-typed newline)
    - the compiled pattern's DOTALL flag (covers a global inline flag like
      (?s) or (?is), in any letter order)
    - a *scoped* inline flag group containing "s", e.g. (?s:...) or
      (?is:...) -- these are NOT reflected in the compiled pattern's
      .flags (Python only folds whole-pattern/global inline flags there),
      so they need their own textual check
    """
    for rule in profile.rules:
        if not rule.enabled or rule.pattern_type != "regex":
            continue
        compiled = re.compile(rule.pattern)
        looks_multiline = (
            "\n" in rule.pattern
            or "\\n" in rule.pattern
            or bool(compiled.flags & re.DOTALL)
            or bool(_SCOPED_DOTALL_RE.search(rule.pattern))
        )
        if looks_multiline:
            print(
                f"警告: ルール '{rule.name}' は複数行にまたがるマッチを意図している可能性があります。"
                f"--stream モードでは1行ずつ処理されるため、このルールは正しく機能しない場合があります。",
                file=sys.stderr,
            )


def _run_streaming(args: argparse.Namespace, profile: RuleProfile) -> int:
    store = MappingStore()
    _warn_about_multiline_rules(profile)

    _reconfigure_encoding(sys.stdin, args.encoding)
    _reconfigure_encoding(sys.stdout, args.encoding)

    try:
        for line in sys.stdin:
            masked, store = apply_profile(line, profile, store)
            sys.stdout.write(masked)
            sys.stdout.flush()
    except UnicodeDecodeError as exc:
        print(
            f"標準入力の読み込みに失敗しました(文字エンコーディングが "
            f"--encoding='{args.encoding}' と一致しているか確認してください): {exc}",
            file=sys.stderr,
        )
        return 1
    except UnicodeEncodeError as exc:
        print(
            f"標準出力への書き込みに失敗しました(--encoding='{args.encoding}' "
            f"を確認してください): {exc}",
            file=sys.stderr,
        )
        return 1
    except OSError:
        # 下流(パイプの読み込み側)が早期に終了した場合(例: `| head` 等)。
        # --streamは長時間実行プロセスをパイプする用途が主眼のため、これは
        # 異常ではなく正常な終了として扱う。Pythonがプロセス終了時に行う
        # 標準出力の自動flushで同じエラーが再発しないよう、以降の書き込み先を
        # devnullに差し替えておく(実ファイルディスクリプタを持たないテスト用
        # の差し替えストリームではfileno()が使えないため、その場合は何もしない)。
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return 0

    return 0


def _run_batch(args: argparse.Namespace, profile) -> int:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    store = MappingStore()
    for input_path_str in args.batch:
        if args.reset_mapping_per_file:
            store = MappingStore()

        input_path = Path(input_path_str)
        text = _read_input_file(input_path, args.encoding)
        if text is None:
            return 1
        masked, store = apply_profile(text, profile, store)

        output_path = output_dir / f"{input_path.stem}.masked{input_path.suffix}"
        if not _write_output_file(output_path, masked, args.encoding):
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
