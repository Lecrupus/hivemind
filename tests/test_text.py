from hivemind.text import command_key, error_signature, extract_entities, is_inspect_only, normalize_command, redact


def test_command_key_normalises_runners():
    assert command_key("uv run pytest -q") == "pytest"
    assert command_key("python -m pytest tests/") == "pytest"
    assert command_key("FOO=1 npm run build") == "npm build"
    assert command_key("docker compose up -d db") == "docker compose"
    assert command_key("npx vitest run") == "vitest"


def test_normalize_command_treats_equivalent_steps_as_equal():
    assert normalize_command("uv run pytest -q") == normalize_command("pytest -q")
    assert normalize_command("python -m pytest -q") == normalize_command("pytest -q")


def test_inspect_only_commands_are_not_procedure_steps():
    assert is_inspect_only("ls -la")
    assert is_inspect_only("git status")
    assert not is_inspect_only("docker compose up -d db")


def test_error_signature_prefers_root_cause_over_summary():
    err = 'E   psycopg.OperationalError: connection to server at "localhost" (127.0.0.1), port 5432 failed\n1 failed, 41 errors in 3.2s'
    sig = error_signature(err)
    assert "OperationalError" in sig
    assert "41 errors" not in sig


def test_redact_removes_secrets():
    text = "use sk-abcdefghijklmnopqrstuvwx and password=hunter22 at postgres://app:s3cret@db/x"
    out = redact(text)
    assert "sk-abcdef" not in out and "hunter22" not in out and "s3cret" not in out


def test_extract_entities_finds_files_and_commands():
    ents = {e["id"]: e["type"] for e in extract_entities("Edit `src/payments/refunds.py` then run `uv run pytest -q`")}
    assert ents.get("src/payments/refunds.py") == "file"
    assert ents.get("pytest") == "command"
