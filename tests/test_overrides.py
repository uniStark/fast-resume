"""Tests for the title overrides store."""

from fast_resume.overrides import TitleOverrides


def test_set_and_get(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("sess-1", "My custom title")
    assert store.get("sess-1") == "My custom title"


def test_get_missing_returns_none(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    assert store.get("nope") is None


def test_clear_removes_entry(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("sess-1", "Custom")
    store.clear("sess-1")
    assert store.get("sess-1") is None


def test_clear_missing_is_noop(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.clear("nope")  # must not raise
    assert store.get("nope") is None


def test_persists_across_instances(temp_dir):
    path = temp_dir / "overrides.json"
    TitleOverrides(path=path).set("sess-1", "Persisted")
    assert TitleOverrides(path=path).get("sess-1") == "Persisted"


def test_all_returns_mapping(temp_dir):
    store = TitleOverrides(path=temp_dir / "overrides.json")
    store.set("a", "A")
    store.set("b", "B")
    assert store.all() == {"a": "A", "b": "B"}


def test_corrupt_json_falls_back_to_empty(temp_dir):
    path = temp_dir / "overrides.json"
    path.write_text("{ this is not valid json")
    store = TitleOverrides(path=path)
    assert store.all() == {}
    # still usable after corruption
    store.set("sess-1", "Recovered")
    assert store.get("sess-1") == "Recovered"


def test_missing_file_is_empty(temp_dir):
    store = TitleOverrides(path=temp_dir / "does_not_exist.json")
    assert store.all() == {}


def test_non_dict_json_falls_back_to_empty(temp_dir):
    path = temp_dir / "overrides.json"
    path.write_text("[1, 2, 3]")  # valid JSON, wrong shape
    store = TitleOverrides(path=path)
    assert store.all() == {}
