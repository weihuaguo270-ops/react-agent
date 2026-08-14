from pathlib import Path

from react_agent.paths import data_dir, migrate_legacy_file, runtime_dir, runtime_file


def test_data_directory_override_is_shared_by_runtime_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_DATA_DIR", str(tmp_path))

    assert data_dir() == tmp_path.resolve()
    assert runtime_file("memory.json") == tmp_path / "memory.json"
    assert runtime_dir("trajectories") == tmp_path / "trajectories"


def test_data_directory_falls_back_when_platform_default_is_not_writable(monkeypatch, tmp_path):
    monkeypatch.delenv("REACT_AGENT_DATA_DIR", raising=False)
    monkeypatch.setattr("react_agent.paths._platform_name", lambda: "nt")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "blocked"))
    monkeypatch.setattr("react_agent.paths._directory_is_writable", lambda path: False)
    assert data_dir() == Path(__import__("tempfile").gettempdir()) / "react-agent"


def test_dedicated_artifact_override_wins(tmp_path, monkeypatch):
    custom = tmp_path / "custom" / "memory.json"
    monkeypatch.setenv("REACT_AGENT_MEMORY_FILE", str(custom))

    assert runtime_file("memory.json", env_var="REACT_AGENT_MEMORY_FILE") == custom


def test_legacy_file_is_migrated_without_modifying_source(tmp_path):
    legacy = tmp_path / "package" / "memory.json"
    target = tmp_path / "data" / "memory.json"
    legacy.parent.mkdir()
    legacy.write_text('{"facts": ["legacy"]}', encoding="utf-8")

    migrate_legacy_file(target, legacy)

    assert target.read_text(encoding="utf-8") == legacy.read_text(encoding="utf-8")
    assert legacy.exists()
