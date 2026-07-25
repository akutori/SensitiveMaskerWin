import io
import json
import sys

import pytest

from cli.main import main
from tests.fixtures.synthetic_logs import FAKE_PHONE_1


@pytest.fixture
def profile_path(tmp_path):
    """Self-contained test profile (phone-number rule matching FAKE_PHONE_1).

    CLI tests build their own profile file rather than depending on any
    shipped rules/*.json, since the CLI must work with any profile the
    user points it at.
    """
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "phone",
                "pattern_type": "regex",
                "pattern": r"0\d{1,4}-\d{1,4}-\d{3,4}",
                "mode": "random",
                "prefix": "__MASK_PHONE_",
            }
        ],
    }
    path = tmp_path / "test_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _run(monkeypatch, capsys, argv, stdin_text=None):
    if stdin_text is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
    exit_code = main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_cli_stdin_stdout_masks_text(monkeypatch, capsys, profile_path):
    exit_code, out, _ = _run(
        monkeypatch,
        capsys,
        ["--profile", profile_path],
        stdin_text=f"caller={FAKE_PHONE_1}\n",
    )
    assert exit_code == 0
    assert "__MASK_PHONE_1__" in out
    assert FAKE_PHONE_1 not in out


def test_cli_stdin_decodes_as_utf8_regardless_of_stream_default_encoding(
    monkeypatch, capsys, profile_path
):
    # Regression test for piped Japanese text getting mangled on Windows: a
    # real TextIOWrapper's default text encoding follows the console
    # codepage, which may not be UTF-8 even though the bytes sent to stdin
    # are UTF-8 (e.g. PowerShell piping). Simulate that mismatch directly
    # rather than depending on the actual OS console codepage.
    raw_utf8_bytes = f"caller={FAKE_PHONE_1} 日本語\n".encode("utf-8")
    stdin_stream = io.TextIOWrapper(io.BytesIO(raw_utf8_bytes), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", stdin_stream)

    exit_code = main(["--profile", profile_path])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "日本語" in out
    assert "__MASK_PHONE_1__" in out


def test_cli_stdin_decode_error_exits_cleanly_without_traceback(
    monkeypatch, capsys, profile_path
):
    # Regression guard: forcing stdin to --encoding's default (utf-8) must
    # not turn genuinely non-UTF-8 piped input (e.g. cp932/Shift_JIS, which
    # decoded fine before stdin/stdout were force-reconfigured) into an
    # unhandled crash. It should fail the same clean, no-traceback way
    # ProfileLoadError does, not leak a raw Python traceback to the user.
    raw_cp932_bytes = "caller=日本語のテスト\n".encode("cp932")
    stdin_stream = io.TextIOWrapper(io.BytesIO(raw_cp932_bytes), encoding="cp932")
    monkeypatch.setattr(sys, "stdin", stdin_stream)

    exit_code = main(["--profile", profile_path])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_file_input_output(tmp_path, profile_path):
    input_path = tmp_path / "in.log"
    output_path = tmp_path / "out.log"
    input_path.write_text(f"caller={FAKE_PHONE_1}\n", encoding="utf-8")

    exit_code = main(
        [
            "--profile", profile_path,
            "--input", str(input_path),
            "--output", str(output_path),
        ]
    )

    assert exit_code == 0
    masked = output_path.read_text(encoding="utf-8")
    assert "__MASK_PHONE_1__" in masked
    assert FAKE_PHONE_1 not in masked


def test_cli_input_file_not_found_exits_cleanly_without_traceback(tmp_path, capsys, profile_path):
    # Regression guard: --input pointing at a missing file must fail the
    # same clean, no-traceback way as an invalid --profile, not leak a raw
    # FileNotFoundError traceback (found via manual exe verification).
    missing_path = tmp_path / "does_not_exist.log"

    exit_code = main(["--profile", profile_path, "--input", str(missing_path)])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_input_file_decode_error_exits_cleanly_without_traceback(tmp_path, capsys, profile_path):
    # Regression guard: an --input file whose bytes don't match --encoding
    # (default utf-8) must fail cleanly, not crash with a raw
    # UnicodeDecodeError traceback (same class of bug as the stdin case,
    # but for file-based --input; found via manual exe verification).
    bad_path = tmp_path / "cp932.log"
    bad_path.write_bytes("caller=日本語のテスト\n".encode("cp932"))

    exit_code = main(["--profile", profile_path, "--input", str(bad_path)])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_batch_input_file_not_found_exits_cleanly_without_traceback(
    tmp_path, capsys, profile_path
):
    missing_path = tmp_path / "does_not_exist.log"

    exit_code = main(
        [
            "--profile", profile_path,
            "--batch", str(missing_path),
            "--output-dir", str(tmp_path / "out"),
        ]
    )
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_missing_profile_arg_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err.lower()


def test_cli_invalid_profile_path_exits_nonzero_with_clean_message(capsys):
    exit_code = main(["--profile", "does_not_exist.json"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err


def test_cli_batch_mode_shared_mapping_across_files(tmp_path, profile_path):
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    file_a.write_text(f"caller={FAKE_PHONE_1}\n", encoding="utf-8")
    file_b.write_text(f"caller={FAKE_PHONE_1}\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "--profile", profile_path,
            "--batch", str(file_a), str(file_b),
            "--output-dir", str(output_dir),
        ]
    )

    assert exit_code == 0
    out_a = (output_dir / "a.masked.log").read_text(encoding="utf-8")
    out_b = (output_dir / "b.masked.log").read_text(encoding="utf-8")
    assert "__MASK_PHONE_1__" in out_a
    # Shared MappingStore: same original value across files reuses the
    # same dummy (counter does not advance to _2__ for the second file).
    assert "__MASK_PHONE_1__" in out_b


def test_cli_batch_mode_reset_mapping_per_file(tmp_path, profile_path):
    file_a = tmp_path / "a.log"
    file_b = tmp_path / "b.log"
    file_a.write_text(f"caller={FAKE_PHONE_1}\n", encoding="utf-8")
    file_b.write_text(f"caller={FAKE_PHONE_1}\n", encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = main(
        [
            "--profile", profile_path,
            "--batch", str(file_a), str(file_b),
            "--output-dir", str(output_dir),
            "--reset-mapping-per-file",
        ]
    )

    assert exit_code == 0
    out_a = (output_dir / "a.masked.log").read_text(encoding="utf-8")
    out_b = (output_dir / "b.masked.log").read_text(encoding="utf-8")
    # Reset per file: counter restarts at _1__ in both files independently.
    assert "__MASK_PHONE_1__" in out_a
    assert "__MASK_PHONE_1__" in out_b


def test_cli_batch_requires_output_dir(tmp_path, profile_path):
    file_a = tmp_path / "a.log"
    file_a.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main(["--profile", profile_path, "--batch", str(file_a)])
    assert exc_info.value.code == 2


def test_cli_batch_and_input_mutually_exclusive(tmp_path, profile_path):
    file_a = tmp_path / "a.log"
    file_a.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--profile", profile_path,
                "--input", str(file_a),
                "--batch", str(file_a),
                "--output-dir", str(tmp_path / "out"),
            ]
        )
    assert exc_info.value.code == 2


# --- --stream (issue #13) --------------------------------------------------
# Opt-in flag, stdin/stdout only: existing batch/single behavior stays the
# default. Streaming reads stdin line by line, masking and flushing each
# line immediately so output appears incrementally while piping a
# long-running process, instead of waiting for EOF.


@pytest.fixture
def multiline_profile_path(tmp_path):
    """Profile with a regex rule whose pattern is written to span multiple
    lines (inline (?s) DOTALL flag) -- the kind of custom rule --stream's
    per-line processing cannot correctly apply, used to test the startup
    warning heuristic.
    """
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "multiline_block",
                "pattern_type": "regex",
                "pattern": r"(?s)-----BEGIN-----.*?-----END-----",
                "mode": "fixed",
                "fixed_value": "__MASK_BLOCK__",
            }
        ],
    }
    path = tmp_path / "multiline_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_stream_masks_each_line(monkeypatch, capsys, profile_path):
    stdin_text = f"a={FAKE_PHONE_1}\nb=unrelated\nc={FAKE_PHONE_1}\n"
    exit_code, out, _ = _run(
        monkeypatch, capsys, ["--profile", profile_path, "--stream"], stdin_text=stdin_text
    )
    assert exit_code == 0
    assert out == "a=__MASK_PHONE_1__\nb=unrelated\nc=__MASK_PHONE_1__\n"


def test_cli_stream_reuses_same_dummy_across_lines(monkeypatch, capsys, profile_path):
    # MappingStore continuity across the streaming loop: the same original
    # value on two different lines must map to the same dummy, not a fresh
    # counter per line.
    stdin_text = f"a={FAKE_PHONE_1}\nb={FAKE_PHONE_1}\n"
    exit_code, out, _ = _run(
        monkeypatch, capsys, ["--profile", profile_path, "--stream"], stdin_text=stdin_text
    )
    assert exit_code == 0
    assert out.count("__MASK_PHONE_1__") == 2
    assert "__MASK_PHONE_2__" not in out


def test_cli_stream_flushes_output_after_each_line(monkeypatch, profile_path):
    # The entire point of --stream is that output appears incrementally,
    # not only after the whole input is consumed -- verify flush() is
    # actually called once per line, not just once at the end.
    stdin_text = f"a={FAKE_PHONE_1}\nb={FAKE_PHONE_1}\nc={FAKE_PHONE_1}\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

    class _FlushSpyStream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.flush_count = 0

        def flush(self):
            self.flush_count += 1
            return super().flush()

    fake_stdout = _FlushSpyStream()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    exit_code = main(["--profile", profile_path, "--stream"])

    assert exit_code == 0
    assert fake_stdout.flush_count == 3
    fake_stdout.seek(0)
    assert fake_stdout.read().count("__MASK_PHONE_1__") == 3


def test_cli_stream_incompatible_with_batch(tmp_path, capsys, profile_path):
    file_a = tmp_path / "a.log"
    file_a.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--profile", profile_path,
                "--stream",
                "--batch", str(file_a),
                "--output-dir", str(tmp_path / "out"),
            ]
        )
    assert exc_info.value.code == 2
    assert "--stream" in capsys.readouterr().err


def test_cli_stream_batch_error_takes_priority_even_without_output_dir(tmp_path, capsys, profile_path):
    # Regression guard for validation ORDER: --stream's own mutual-exclusion
    # check must run before --batch's separate (missing --output-dir) check,
    # so the user immediately learns --stream itself is the real problem
    # instead of first being told to add --output-dir and only discovering
    # the --stream incompatibility on a second run.
    file_a = tmp_path / "a.log"
    file_a.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main(["--profile", profile_path, "--stream", "--batch", str(file_a)])
    assert exc_info.value.code == 2
    assert "--stream" in capsys.readouterr().err


def test_cli_stream_incompatible_with_input(tmp_path, capsys, profile_path):
    file_a = tmp_path / "a.log"
    file_a.write_text("nothing\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        main(["--profile", profile_path, "--stream", "--input", str(file_a)])
    assert exc_info.value.code == 2
    assert "--stream" in capsys.readouterr().err


def test_cli_stream_incompatible_with_output(tmp_path, capsys, profile_path):
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--profile", profile_path,
                "--stream",
                "--output", str(tmp_path / "out.log"),
            ]
        )
    assert exc_info.value.code == 2
    assert "--stream" in capsys.readouterr().err


def test_cli_stream_incompatible_with_reset_mapping_per_file(capsys, profile_path):
    with pytest.raises(SystemExit) as exc_info:
        main(["--profile", profile_path, "--stream", "--reset-mapping-per-file"])
    assert exc_info.value.code == 2
    assert "--stream" in capsys.readouterr().err


def test_cli_stream_warns_about_multiline_regex_rule(monkeypatch, capsys, multiline_profile_path):
    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", multiline_profile_path, "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert "multiline_block" in err
    assert "--stream" in err


def test_cli_stream_no_warning_for_single_line_rules(monkeypatch, capsys, profile_path):
    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", profile_path, "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert err == ""


def test_cli_stream_no_warning_for_literal_pattern_containing_dotall_markers(
    monkeypatch, capsys, tmp_path
):
    # Negative test paired with the multiline-warning test above:
    # pattern_type="literal" is never regex-interpreted, so a literal
    # pattern that happens to contain "(?s)" text must NOT trigger the
    # multiline-regex warning.
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "literal_with_dotall_lookalike_text",
                "pattern_type": "literal",
                "pattern": "(?s)literal-not-regex",
                "mode": "fixed",
                "fixed_value": "__MASK__",
            }
        ],
    }
    path = tmp_path / "literal_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", str(path), "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert err == ""


def test_cli_stream_warns_about_newline_escape_token_in_pattern(monkeypatch, capsys, tmp_path):
    # Adversarial-review follow-up: the heuristic originally only detected a
    # raw embedded newline character or the literal "(?s)" substring. The
    # \n *escape token* (backslash + "n", two characters) is the realistic,
    # idiomatic way anyone would author a multi-line-spanning pattern in a
    # JSON profile -- and the ONLY way reachable through the GUI at all,
    # since its pattern field is a single-line Entry that cannot receive a
    # literally-typed newline character.
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "private_key_block",
                "pattern_type": "regex",
                "pattern": "-----BEGIN-----\\n.*\\n-----END-----",
                "mode": "fixed",
                "fixed_value": "__MASK_KEY__",
            }
        ],
    }
    path = tmp_path / "escape_newline_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", str(path), "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert "private_key_block" in err


def test_cli_stream_warns_about_scoped_dotall_flag_group(monkeypatch, capsys, tmp_path):
    # Adversarial-review follow-up: a *scoped* inline flag group like
    # (?s:...) matches across newlines exactly like the global (?s) flag,
    # but Python only folds whole-pattern/global inline flags into the
    # compiled Pattern's .flags -- group-scoped flags are excluded, and the
    # literal "(?s)" substring check doesn't match "(?s:" either.
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "scoped_dotall_block",
                "pattern_type": "regex",
                "pattern": "(?s:BEGIN.*END)",
                "mode": "fixed",
                "fixed_value": "__MASK__",
            }
        ],
    }
    path = tmp_path / "scoped_dotall_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", str(path), "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert "scoped_dotall_block" in err


def test_cli_stream_no_warning_for_disabled_multiline_rule(monkeypatch, capsys, tmp_path):
    # Negative test: a disabled rule is never applied, so it must not
    # trigger the multiline warning either.
    data = {
        "profile_name": "test",
        "rules": [
            {
                "name": "disabled_multiline",
                "pattern_type": "regex",
                "pattern": "(?s)BEGIN.*END",
                "mode": "fixed",
                "fixed_value": "__MASK__",
                "enabled": False,
            }
        ],
    }
    path = tmp_path / "disabled_multiline_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    exit_code, _out, err = _run(
        monkeypatch, capsys, ["--profile", str(path), "--stream"], stdin_text="x\n"
    )
    assert exit_code == 0
    assert err == ""


def test_cli_stream_stdin_decode_error_exits_cleanly_without_traceback(
    monkeypatch, capsys, profile_path
):
    # --stream's own regression guard, mirroring the existing single-mode
    # test: non-UTF-8 piped input must fail cleanly, not crash with a raw
    # UnicodeDecodeError traceback.
    raw_cp932_bytes = "caller=日本語のテスト\n".encode("cp932")
    stdin_stream = io.TextIOWrapper(io.BytesIO(raw_cp932_bytes), encoding="cp932")
    monkeypatch.setattr(sys, "stdin", stdin_stream)

    exit_code = main(["--profile", profile_path, "--stream"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_stream_stdout_encode_error_exits_cleanly_without_traceback(
    monkeypatch, capsys, profile_path
):
    # Mirror of the decode-error test above, for the write side: masked
    # output containing a character that doesn't fit --encoding must fail
    # cleanly, not crash with a raw UnicodeEncodeError traceback.
    monkeypatch.setattr(sys, "stdin", io.StringIO("caller=日本語のテスト\n"))
    stdout_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", stdout_stream)

    exit_code = main(["--profile", profile_path, "--stream", "--encoding", "ascii"])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "Traceback" not in err


def test_cli_stream_exits_cleanly_when_downstream_pipe_closes(monkeypatch, profile_path):
    # Adversarial-review follow-up: the canonical --stream use case is
    # piping into another process that may stop reading early (e.g.
    # `producer | cli.main --stream | head -n 2`). Writing to a closed pipe
    # must not crash with a raw, unhandled OSError traceback -- this is
    # exactly what --stream is for (a long-running pipe), so it must
    # terminate cleanly instead.
    stdin_text = f"a={FAKE_PHONE_1}\nb={FAKE_PHONE_1}\nc={FAKE_PHONE_1}\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

    class _BrokenPipeStream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.write_count = 0

        def write(self, data):
            self.write_count += 1
            if self.write_count > 2:
                raise OSError(22, "Invalid argument")
            return super().write(data)

    fake_stdout = _BrokenPipeStream()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    exit_code = main(["--profile", profile_path, "--stream"])

    assert exit_code == 0
    fake_stdout.seek(0)
    # The two lines written before the pipe broke must survive; no
    # exception should have propagated out of main().
    assert fake_stdout.read().count("__MASK_PHONE_1__") == 2
