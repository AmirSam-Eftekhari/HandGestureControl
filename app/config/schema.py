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

    # Custom (user-recorded) gesture matching -- see
    # app/gestures/custom_gestures.py. Lower = stricter match required.
    custom_gesture_match_threshold: float = 0.35

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

    cfg = AppConfig(
        camera=camera,
        detection=detection,
        smoothing=smoothing,
        gestures=gestures,
        visualization=visualization,
        performance=performance,
        pinch_volume=pinch_volume,
        theme=theme,
    )
    return validate_and_clamp(cfg)


def _clamp(value, low, high, default):
    """Clamps a number into [low, high]; falls back to `default` for
    anything that isn't even a usable number (wrong type, NaN, etc) --
    a hand-edited or corrupted config file can contain arbitrary JSON
    values in a numeric field, and this must never raise."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN check without importing math for one use
        return default
    return max(low, min(high, value))


def validate_and_clamp(cfg: AppConfig) -> AppConfig:
    """Defends against invalid configuration states -- out-of-range
    thresholds, non-positive sizes, inverted min/max pairs, unknown
    enum-like strings -- regardless of whether they came from a
    corrupted file, a value from an older/newer app version, or a
    hand-edited settings.json. This runs on every config load (and on
    fresh defaults, as a cheap self-check) so the rest of the app can
    trust these values are always sane without re-validating them
    itself. Never raises; anything it can't make sense of is replaced
    with a safe default rather than rejected wholesale, so one bad field
    doesn't cost the user their whole settings file.
    """
    c = cfg.camera
    c.device_index = int(_clamp(c.device_index, 0, 64, 0))
    c.requested_width = int(_clamp(c.requested_width, 160, 7680, 1280))
    c.requested_height = int(_clamp(c.requested_height, 120, 4320, 720))
    c.requested_fps = int(_clamp(c.requested_fps, 1, 240, 30))

    d = cfg.detection
    d.max_hands = int(_clamp(d.max_hands, 1, 2, 2))
    d.detection_confidence = _clamp(d.detection_confidence, 0.05, 0.99, 0.6)
    d.presence_confidence = _clamp(d.presence_confidence, 0.05, 0.99, 0.5)
    d.tracking_confidence = _clamp(d.tracking_confidence, 0.05, 0.99, 0.5)
    d.max_missed_frames = int(_clamp(d.max_missed_frames, 1, 300, 8))
    if not isinstance(d.model_path, str) or not d.model_path.strip():
        d.model_path = DetectionConfig().model_path
    if not isinstance(d.backend, str) or not d.backend.strip():
        d.backend = DetectionConfig().backend

    s = cfg.smoothing
    if s.method not in ("one_euro", "ema"):
        s.method = "one_euro"
    s.one_euro_min_cutoff = _clamp(s.one_euro_min_cutoff, 0.01, 50.0, 1.2)
    s.one_euro_beta = _clamp(s.one_euro_beta, 0.0, 200.0, 12.0)
    s.one_euro_d_cutoff = _clamp(s.one_euro_d_cutoff, 0.01, 50.0, 1.0)
    s.ema_alpha = _clamp(s.ema_alpha, 0.01, 1.0, 0.5)

    t = cfg.gestures.thresholds
    t.curl_extended_max = _clamp(t.curl_extended_max, 0.01, 0.95, 0.35)
    t.curl_folded_min = _clamp(t.curl_folded_min, 0.05, 0.99, 0.65)
    if t.curl_extended_max >= t.curl_folded_min:
        # An inverted or overlapping pair can't be interpreted sensibly
        # -- reset both to the factory defaults rather than guess at a
        # "fixed" pair that might not reflect what the user intended.
        t.curl_extended_max, t.curl_folded_min = 0.35, 0.65
    t.thumb_extended_angle_deg = _clamp(t.thumb_extended_angle_deg, 1.0, 89.0, 35.0)
    t.static_confirm_ms = _clamp(t.static_confirm_ms, 0.0, 5000.0, 120.0)
    t.static_min_confidence = _clamp(t.static_min_confidence, 0.01, 0.99, 0.55)
    t.pinch_on_ratio = _clamp(t.pinch_on_ratio, 0.02, 0.95, 0.32)
    t.pinch_off_ratio = _clamp(t.pinch_off_ratio, t.pinch_on_ratio, 1.0, max(0.42, t.pinch_on_ratio + 0.05))
    t.custom_gesture_match_threshold = _clamp(t.custom_gesture_match_threshold, 0.02, 3.0, 0.35)
    t.snap_velocity_threshold = _clamp(t.snap_velocity_threshold, 0.1, 100.0, 6.5)
    t.snap_min_pre_distance = _clamp(t.snap_min_pre_distance, 0.01, 2.0, 0.12)
    t.snap_max_trigger_distance = _clamp(t.snap_max_trigger_distance, 0.001, t.snap_min_pre_distance, min(0.06, t.snap_min_pre_distance))
    t.snap_window_ms = _clamp(t.snap_window_ms, 20.0, 5000.0, 180.0)
    t.snap_cooldown_ms = _clamp(t.snap_cooldown_ms, 0.0, 10000.0, 450.0)
    t.default_action_cooldown_ms = _clamp(t.default_action_cooldown_ms, 0.0, 10000.0, 400.0)

    for mapping in cfg.gestures.mappings:
        mapping.cooldown_ms = _clamp(mapping.cooldown_ms, 0.0, 20000.0, 400.0)
        mapping.sensitivity = _clamp(mapping.sensitivity, 0.01, 10.0, 1.0)
        mapping.enabled = bool(mapping.enabled)

    v = cfg.visualization
    if v.mode not in ("minimal", "skeleton", "detailed", "debug"):
        v.mode = "skeleton"
    v.trail_length = int(_clamp(v.trail_length, 2, 200, 18))

    p = cfg.performance
    p.target_processing_fps = int(_clamp(p.target_processing_fps, 1, 240, 30))

    pv = cfg.pinch_volume
    pv.min_distance_ratio = _clamp(pv.min_distance_ratio, 0.0, 5.0, 0.08)
    pv.max_distance_ratio = _clamp(pv.max_distance_ratio, pv.min_distance_ratio + 0.01, 10.0, max(0.55, pv.min_distance_ratio + 0.1))
    pv.smoothing_alpha = _clamp(pv.smoothing_alpha, 0.01, 1.0, 0.25)
    pv.dead_zone_percent = _clamp(pv.dead_zone_percent, 0.0, 50.0, 1.5)

    if cfg.theme not in ("dark", "light"):
        cfg.theme = "dark"

    return cfg
