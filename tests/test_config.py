import json

from app.config.defaults import DEFAULT_MAPPINGS
from app.config.schema import AppConfig, config_from_dict, config_to_dict
from app.config.settings import load_config, save_config


def test_default_config_has_seeded_mappings(tmp_path):
    cfg = load_config(tmp_path / "settings.json")
    assert len(cfg.gestures.mappings) == len(DEFAULT_MAPPINGS)
    assert cfg.gestures.mappings[0].gesture_id == "pinch"


def test_round_trip_preserves_edits(tmp_path):
    path = tmp_path / "settings.json"
    cfg = load_config(path)
    cfg.camera.mirror = False
    cfg.camera.device_index = 2
    cfg.detection.max_hands = 1
    cfg.gestures.thresholds.static_confirm_ms = 250.0
    cfg.visualization.mode = "debug"
    cfg.gestures.mappings[0].enabled = False

    save_config(cfg, path)
    reloaded = load_config(path)

    assert reloaded.camera.mirror is False
    assert reloaded.camera.device_index == 2
    assert reloaded.detection.max_hands == 1
    assert reloaded.gestures.thresholds.static_confirm_ms == 250.0
    assert reloaded.visualization.mode == "debug"
    assert reloaded.gestures.mappings[0].enabled is False


def test_missing_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "does_not_exist.json"
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert cfg.camera.mirror is True  # default


def test_corrupt_file_falls_back_to_defaults_and_is_backed_up(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not valid json!!!")

    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    backup = path.with_suffix(".corrupt.json")
    assert backup.exists()
    assert backup.read_text() == "{not valid json!!!"


def test_partial_file_fills_in_missing_fields_with_defaults(tmp_path):
    path = tmp_path / "settings.json"
    # Simulates an older config file saved before new fields were added.
    partial = {"camera": {"mirror": False}}
    path.write_text(json.dumps(partial))

    cfg = load_config(path)
    assert cfg.camera.mirror is False
    assert cfg.camera.requested_width == 1280  # untouched field keeps its default
    assert len(cfg.gestures.mappings) == len(DEFAULT_MAPPINGS)  # backfilled since missing


def test_config_to_dict_and_from_dict_round_trip():
    cfg = AppConfig()
    cfg.pinch_volume.dead_zone_percent = 7.5
    data = config_to_dict(cfg)
    rebuilt = config_from_dict(data)
    assert rebuilt.pinch_volume.dead_zone_percent == 7.5
    assert rebuilt.theme == cfg.theme
