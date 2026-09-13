import json

from app.config.custom_gestures_store import load_custom_gestures, save_custom_gestures
from app.gestures.custom_gestures import CustomGestureTemplate


def _template(id_="abc123", name="My Gesture"):
    return CustomGestureTemplate(
        id=id_,
        name=name,
        curl_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
        thumb_abduction_deg=42.0,
        pinch_distance_norm=0.8,
        recorded_handedness="Left",
    )


def test_missing_file_returns_empty_list(tmp_path):
    assert load_custom_gestures(tmp_path / "does_not_exist.json") == []


def test_round_trip_preserves_all_fields(tmp_path):
    path = tmp_path / "custom_gestures.json"
    original = _template()
    save_custom_gestures([original], path)

    loaded = load_custom_gestures(path)
    assert len(loaded) == 1
    restored = loaded[0]
    assert restored.id == original.id
    assert restored.name == original.name
    assert restored.curl_vector == original.curl_vector
    assert restored.thumb_abduction_deg == original.thumb_abduction_deg
    assert restored.pinch_distance_norm == original.pinch_distance_norm
    assert restored.recorded_handedness == original.recorded_handedness


def test_multiple_templates_round_trip(tmp_path):
    path = tmp_path / "custom_gestures.json"
    templates = [_template("a", "First"), _template("b", "Second")]
    save_custom_gestures(templates, path)

    loaded = load_custom_gestures(path)
    assert {t.id for t in loaded} == {"a", "b"}


def test_corrupt_file_falls_back_to_empty_and_is_backed_up(tmp_path):
    path = tmp_path / "custom_gestures.json"
    path.write_text("{not valid json!!!")

    loaded = load_custom_gestures(path)
    assert loaded == []
    backup = path.with_suffix(".corrupt.json")
    assert backup.exists()


def test_non_list_top_level_is_treated_as_corrupt(tmp_path):
    path = tmp_path / "custom_gestures.json"
    path.write_text(json.dumps({"not": "a list"}))

    assert load_custom_gestures(path) == []


def test_one_malformed_entry_does_not_break_the_others(tmp_path):
    path = tmp_path / "custom_gestures.json"
    payload = [
        {
            "id": "good1",
            "name": "Good",
            "curl_vector": [0.1, 0.2, 0.3, 0.4, 0.5],
            "thumb_abduction_deg": 10.0,
            "pinch_distance_norm": 0.5,
            "recorded_handedness": "Right",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {"id": "bad1", "curl_vector": [1, 2]},  # wrong length, missing fields
        "totally wrong type",
    ]
    path.write_text(json.dumps(payload))

    loaded = load_custom_gestures(path)
    assert len(loaded) == 1
    assert loaded[0].id == "good1"


def test_curl_values_are_clamped_into_valid_range(tmp_path):
    path = tmp_path / "custom_gestures.json"
    payload = [
        {
            "id": "x",
            "name": "Weird",
            "curl_vector": [-5.0, 99.0, 0.5, 0.5, 0.5],
            "thumb_abduction_deg": 10.0,
            "pinch_distance_norm": 0.5,
        }
    ]
    path.write_text(json.dumps(payload))

    loaded = load_custom_gestures(path)
    assert len(loaded) == 1
    assert all(0.0 <= v <= 1.0 for v in loaded[0].curl_vector)


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "custom_gestures.json"
    save_custom_gestures([_template()], path)
    assert path.exists()
