"""
Typed configuration schema for the whole application.

Every tunable threshold, timing constant, and UI preference lives here
instead of being scattered through the codebase (see project rule: no
magic numbers). Everything is a plain dataclass so it can be trivially
serialized to/from JSON and validated.

Dataclasses are grouped by subsystem so that a module only needs to import
the slice it cares about (e.g. the smoothing engine imports
``SmoothingConfig``, not the whole app config).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict


@dataclass
class CameraConfig:
    device_index: int = 0
    requested_width: int = 1280
    requested_height: int = 720
    requested_fps: int = 30
    mirror: bool = True
    # If the requested resolution/fps isn't supported, the camera manager
    # falls back to whatever the driver reports rather than failing.
    auto_fallback: bool = True


@dataclass
class DetectionConfig:
    backend: str = "mediapipe_tasks"
    model_path: str = "assets/models/hand_landmarker.task"
    max_hands: int = 2
    detection_confidence: float = 0.6
    presence_confidence: float = 0.5
    tracking_confidence: float = 0.5
    use_gpu: bool = True
    # Number of consecutive frames a hand may go undetected before we
    # consider it "lost" rather than briefly occluded.
    max_missed_frames: int = 8


@dataclass
class SmoothingConfig:
    enabled: bool = True
    # "one_euro" or "ema"
    method: str = "one_euro"
    # One Euro Filter parameters (see app/vision/smoothing.py for the math).
    # min_cutoff trades lag for jitter at low speed; beta reduces lag at
    # high speed (i.e. fast gesture motion snaps to the true position).
    one_euro_min_cutoff: float = 1.2
    one_euro_beta: float = 12.0
    one_euro_d_cutoff: float = 1.0
    # Plain EMA fallback, 0..1, higher = less smoothing.
    ema_alpha: float = 0.5


@dataclass
class GestureThresholds:
    # Finger-state classification.
    curl_extended_max: float = 0.35   # curl ratio below this => extended
    curl_folded_min: float = 0.65     # curl ratio above this => folded
    thumb_extended_angle_deg: float = 35.0

    # Static gesture confirmation: a pose must be classified consistently
    # for this long before it "counts", so a single noisy frame can't
    # trigger an action.
    static_confirm_ms: float = 120.0
    static_min_confidence: float = 0.55

    # Pinch.
    pinch_on_ratio: float = 0.32      # distance / palm_size below => pinching
    pinch_off_ratio: float = 0.42     # hysteresis release threshold

    # Dynamic gesture motion.
    swipe_min_speed: float = 1.8      # normalized units / second
    swipe_min_travel: float = 0.18    # normalized hand-center displacement
    swipe_max_duration_ms: float = 550.0
    wave_min_direction_changes: int = 3
    wave_window_ms: float = 1200.0
    circle_min_radius: float = 0.05
    circle_min_coverage: float = 0.7  # fraction of a full revolution

    # Snap detector.
    snap_velocity_threshold: float = 6.5   # normalized units/second, thumb-middle closing speed
    snap_min_pre_distance: float = 0.12    # fingers must start apart
    snap_max_trigger_distance: float = 0.06
    snap_window_ms: float = 180.0
    snap_cooldown_ms: float = 450.0

    # General action cooldown/debounce applied per gesture id.
    default_action_cooldown_ms: float = 400.0


@dataclass
class VisualizationConfig:
    mode: str = "skeleton"  # minimal | skeleton | detailed | debug
    show_landmarks: bool = True
    show_connections: bool = True
    show_labels: bool = True
    show_confidence: bool = True
    show_motion_trail: bool = False
    trail_length: int = 18


@dataclass
class PerformanceConfig:
    show_fps_overlay: bool = False
    show_latency_overlay: bool = False
    target_processing_fps: int = 30
    # Skip full detector inference on some frames when a lightweight
    # tracker can carry landmarks forward (see FrameSkipPolicy).
    allow_frame_skipping: bool = True


@dataclass
class PinchVolumeConfig:
    enabled_by_default: bool = False
    min_distance_ratio: float = 0.08
    max_distance_ratio: float = 0.55
    smoothing_alpha: float = 0.25
    dead_zone_percent: float = 1.5


@dataclass
class ActionMappingEntry:
    gesture_id: str
    action_id: str
    enabled: bool = True
    cooldown_ms: float = 400.0
    sensitivity: float = 1.0


@dataclass
class GesturesConfig:
    thresholds: GestureThresholds = field(default_factory=GestureThresholds)
    mappings: list = field(default_factory=list)  # list[ActionMappingEntry]


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    smoothing: SmoothingConfig = field(default_factory=SmoothingConfig)
    gestures: GesturesConfig = field(default_factory=GesturesConfig)
    visualization: VisualizationConfig = field(default_factory=VisualizationConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    pinch_volume: PinchVolumeConfig = field(default_factory=PinchVolumeConfig)
    theme: str = "dark"


def _to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_to_dict(v) for v in obj]
    return obj


def config_to_dict(cfg: AppConfig) -> Dict[str, Any]:
    return _to_dict(cfg)


def _dataclass_from_dict(cls, data: Dict[str, Any]):
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if is_dataclass(f.type) if isinstance(f.type, type) else False:
            kwargs[f.name] = _dataclass_from_dict(f.type, value)
        else:
            kwargs[f.name] = value
    return cls(**kwargs)


def config_from_dict(data: Dict[str, Any]) -> AppConfig:
    """Rebuild a full AppConfig from a plain dict, tolerating missing keys
    (so upgrading the app with new settings never breaks an old config file)."""
    camera = CameraConfig(**{**config_to_dict(CameraConfig()), **data.get("camera", {})})
    detection = DetectionConfig(**{**config_to_dict(DetectionConfig()), **data.get("detection", {})})
    smoothing = SmoothingConfig(**{**config_to_dict(SmoothingConfig()), **data.get("smoothing", {})})

    thresholds_data = data.get("gestures", {}).get("thresholds", {})
    thresholds = GestureThresholds(**{**config_to_dict(GestureThresholds()), **thresholds_data})
    mappings_data = data.get("gestures", {}).get("mappings", [])
    mappings = [ActionMappingEntry(**m) for m in mappings_data]
    gestures = GesturesConfig(thresholds=thresholds, mappings=mappings)

    visualization = VisualizationConfig(**{**config_to_dict(VisualizationConfig()), **data.get("visualization", {})})
    performance = PerformanceConfig(**{**config_to_dict(PerformanceConfig()), **data.get("performance", {})})
    pinch_volume = PinchVolumeConfig(**{**config_to_dict(PinchVolumeConfig()), **data.get("pinch_volume", {})})
    theme = data.get("theme", "dark")

    return AppConfig(
        camera=camera,
        detection=detection,
        smoothing=smoothing,
        gestures=gestures,
        visualization=visualization,
        performance=performance,
        pinch_volume=pinch_volume,
        theme=theme,
    )
