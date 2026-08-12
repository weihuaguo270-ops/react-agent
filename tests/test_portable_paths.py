from pathlib import Path

from react_agent.paths import data_dir, migrate_legacy_file, runtime_dir, runtime_file


def test_data_directory_override_is_shared_by_runtime_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("REACT_AGENT_DATA_DIR", str(tmp_path))

    assert data_dir() == tmp_path.resolve()
    assert runtime_file("memory.json") == tmp_path / "memory.json"
    assert runtime_dir("trajectories") == tmp_path / "trajectories"


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
