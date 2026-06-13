from bili_text.cli import EXIT_PARTIAL, build_parser, main


def test_parser_accepts_multiple_uids_and_output_dir():
    parser = build_parser()
    args = parser.parse_args(["123", "456", "123", "--output-dir", "/tmp/out"])

    assert args.uids == ["123", "456", "123"]
    assert args.output_dir == "/tmp/out"


def test_parser_requires_at_least_one_uid(capsys):
    parser = build_parser()
    try:
        parser.parse_args([])
    except SystemExit as exc:
        assert exc.code != 0
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit for missing UID")


def test_main_missing_config_exits_nonzero_without_leaking(capsys):
    exit_code = main(["123"], environ={})

    assert exit_code != 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "Missing required configuration" in combined


def test_main_redacts_secrets_in_runtime_errors(capsys, monkeypatch):
    env = {
        "DASHSCOPE_API_KEY": "sk-should-not-leak",
        "MINIO_ENDPOINT": "https://minio.example.com",
        "MINIO_BUCKET": "bucket",
        "MINIO_ACCESS_KEY": "access-should-not-leak",
        "MINIO_SECRET_KEY": "secret-should-not-leak",
    }

    # Force a startup failure so we exercise the error reporting path.
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda _name: None)

    exit_code = main(["123"], environ=env)
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert exit_code != 0
    assert "sk-should-not-leak" not in combined
    assert "secret-should-not-leak" not in combined


def _all_fakes_deps():
    from bili_text.fakes import DeterministicFakes
    from bili_text.orchestrator import PipelineDeps

    fakes = DeterministicFakes()
    return PipelineDeps(
        bilibili=fakes,
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=fakes,
        renderer=fakes.renderer,
    )


def test_main_runs_orchestrator_with_fakes(capsys, monkeypatch, tmp_path):
    env = {
        "DASHSCOPE_API_KEY": "sk-test",
        "MINIO_ENDPOINT": "https://minio.example.com",
        "MINIO_BUCKET": "bucket",
        "MINIO_ACCESS_KEY": "access",
        "MINIO_SECRET_KEY": "secret",
    }
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", _all_fakes_deps)

    exit_code = main(["111", "--output-dir", str(tmp_path)], environ=env)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Prerequisites OK" in captured.out
    assert "Task complete: 1 success" in captured.out
    assert "完整转写" not in captured.out
    assert any(tmp_path.joinpath("111").iterdir())


def test_main_partial_exit_when_uid_fails(capsys, monkeypatch, tmp_path):
    from bili_text.fakes import DeterministicFakes, FakeFailure
    from bili_text.orchestrator import PipelineDeps

    env = {
        "DASHSCOPE_API_KEY": "sk-test",
        "MINIO_ENDPOINT": "https://minio.example.com",
        "MINIO_BUCKET": "bucket",
        "MINIO_ACCESS_KEY": "access",
        "MINIO_SECRET_KEY": "secret",
    }
    monkeypatch.setattr("bili_text.cli.shutil.which", lambda name: f"/usr/bin/{name}")

    fakes = DeterministicFakes(failures=[FakeFailure(uid="bad", stage="extract")])
    deps = PipelineDeps(
        bilibili=fakes,
        audio=fakes,
        storage=fakes,
        transcriber=fakes,
        summarizer=fakes,
        renderer=fakes.renderer,
    )
    monkeypatch.setattr("bili_text.cli.build_pipeline_deps", lambda: deps)

    exit_code = main(["ok", "bad", "--output-dir", str(tmp_path)], environ=env)
    captured = capsys.readouterr()

    assert exit_code == EXIT_PARTIAL
    assert "Task complete: 1 success, 0 partial, 1 failed" in captured.out
