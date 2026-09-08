# Hand Gesture Control

A real-time hand tracking and gesture control desktop application: two
hands, 21 landmarks each, robust finger-state analysis, static and
dynamic gesture recognition, a continuous pinch-to-volume mode, and a
fully configurable gesture-to-action mapping system — all running
locally, with a premium, custom-designed PySide6 interface.

![status](https://img.shields.io/badge/status-active-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What this is

Most "hand tracking demo" projects are a webcam loop with MediaPipe's
default drawing utilities on top. This is a full application: a layered
architecture that separates camera I/O, detection, tracking, geometry,
gesture recognition, action dispatch, and rendering into independently
testable modules; a real-time pipeline that never blocks the UI and
always processes the newest available frame; and a hand-built design
system instead of default Qt widgets.

It's built to be **extended**, not just run: swap in a different
detector backend, add a new static or dynamic gesture, wire a gesture to
a new system action, or add a new visualization mode — each of those is
a localized change, not a rewrite.

## Key features

- **Two-hand tracking** with stable per-hand identity across frames
  (survives brief occlusion), left/right handedness, and per-hand
  confidence.
- **Robust finger-state analysis** — extended / folded / partial /
  unknown — computed from rotation- and scale-invariant geometry (finger
  "straightness" ratios and joint angles), not axis-aligned pixel rules,
  with dedicated handling for the thumb's different motion geometry.
- **Static gestures**: open palm, fist, pointing, thumbs up/down, peace,
  OK, pinch, three-finger, four-finger — each temporally confirmed
  (must hold for a configurable duration) and edge-triggered (fires once
  per pose, not every frame it's held).
- **Dynamic gestures**: swipe (4 directions), hand wave, and circular
  motion, all detected from a rolling window of hand-center motion, not
  a single frame.
- **Finger-snap detection** using closing velocity + a temporal window +
  cooldown, distinguishing an intentional snap from fingers merely
  resting close together.
- **Pinch-to-volume mode**: thumb-index distance, normalized by hand
  scale, EMA-smoothed, with a dead zone to prevent jittery oscillation —
  a genuinely continuous control, not discrete steps.
- **Configurable gesture → action mapping** with per-mapping enable
  toggle, cooldown, and a live editor UI. Nothing disruptive (media keys,
  volume, keyboard shortcuts) is enabled by default.
- **Temporal smoothing** via a One Euro Filter (adapts to motion speed —
  heavy smoothing when still, minimal lag when moving fast), applied
  independently per landmark per tracked hand.
- **Animated hand-status panel**: two stylized hand glyphs whose five
  fingers individually highlight in real time as your fingers extend and
  fold.
- **Measured performance**, not claimed performance: live FPS, frame
  time, and detection latency, plus a standalone `scripts/benchmark.py`.
- **Local-first and private**: camera frames never leave the machine;
  no cloud service is required for any core feature.
- **Backend-swappable by design**: every module above the detector talks
  to a backend-agnostic `HandObservation`/`FrameResult` model, not
  MediaPipe types directly.

## Supported gestures

| Type    | Gesture                                   |
|---------|--------------------------------------------|
| Static  | Open palm, fist, pointing, thumb up, thumb down, peace/V, OK, pinch, three fingers, four fingers |
| Dynamic | Swipe left/right/up/down, hand wave, circular motion |
| Special | Finger snap, pinch-and-hold (continuous volume control) |

Default gesture → action mappings (edit anytime in **Mapping**):

| Gesture     | Action                          | Enabled by default |
|-------------|----------------------------------|---------------------|
| Pinch       | Continuous volume control        | ✅ |
| Snap        | Take camera snapshot             | ✅ |
| Open palm   | Pause / resume tracking          | ✅ |
| Fist        | Cancel current mode               | off |
| Swipe left/right | Media previous/next         | off |
| Swipe up/down    | Volume step up/down          | off |
| Peace       | Toggle skeleton overlay           | off |
| Wave        | Toggle mirror mode                | off |

## Architecture

```
Camera Capture (own thread)
        │  (always-newest-frame handoff, no queue)
        ▼
Frame Pipeline (own thread)
        │
        ├─ Hand Detector Backend  (MediaPipe Tasks HandLandmarker, swappable)
        ├─ Multi-Hand Tracker     (stable IDs, occlusion tolerance, motion history)
        ├─ Landmark Smoother      (One Euro Filter, per-hand-id state)
        ├─ Geometry Engine        (palm scale/axes, finger straightness, angles)
        ├─ Finger-State Classifier
        ├─ Gesture Engine         (static confirmation, dynamic detection, snap, cooldown)
        ├─ Action Dispatcher      (gesture → action mapping, its own cooldown)
        ├─ Pinch-Volume Controller
        └─ Overlay Renderer       (draws skeleton/labels/trail onto the frame)
        │
        ▼
Qt signal → Main Window (UI thread: camera view, hand-status panel,
                          status bar, toasts, settings, gesture mapping)
```

```
app/
├── main_window.py          # integration point: owns camera + pipeline, wires the UI
├── camera/                 # threaded camera capture, device enumeration
├── vision/                 # backend interface + MediaPipe/mock implementations,
│                            #   landmark model, geometry, finger-state, smoothing
├── tracking/                # multi-hand identity + motion history
├── gestures/                # static/dynamic classifiers, snap, pinch, gesture engine
├── actions/                 # action registry, gesture→action mapping, system actions
├── pipeline/                 # the real-time frame-processing worker/thread
├── ui/                       # design system, widgets, camera view, settings, mapping screen
├── config/                   # typed config schema, defaults, JSON persistence
└── utils/                    # perf monitor, logging, errors, synthetic hand generator
tests/                        # pytest suite, synthetic-landmark fixtures
scripts/                      # model downloader, benchmark mode
```

**Why this separation matters in practice:** the geometry, finger-state,
and gesture-recognition modules only ever see plain dataclasses
(`Landmark`, `HandObservation`) — never a MediaPipe type. That's what
lets the entire test suite run without a camera, a GPU, or even MediaPipe
installed for most of the logic, and it's what makes "swap the detector"
a real, exercised capability rather than a design aspiration: the
included mock backend is a second, working implementation of the same
interface.

## Design decisions worth knowing about

- **Detection backend**: [MediaPipe Tasks `HandLandmarker`](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker),
  run in `VIDEO` mode (synchronous, monotonically increasing timestamps)
  rather than `LIVE_STREAM` (async callback) — this app already does its
  own frame capture and processing on a dedicated worker thread, so a
  synchronous call that returns the result directly is simpler to reason
  about than juggling two separate threading models. GPU delegate is
  tried first and falls back to CPU automatically if unavailable.
- **Frame handling**: neither the camera thread nor the pipeline thread
  queues frames. Each always holds only the *newest* one; if a consumer
  falls behind, older frames are dropped. This is what keeps the preview
  feeling live under load instead of playing catch-up.
- **Finger-state math**: extension/flexion is computed as a "straight-line
  distance ÷ path length" ratio per finger in 3D (preferring MediaPipe's
  metric world landmarks when available), not a comparison of raw pixel
  coordinates — so it stays correct as the hand rotates, tilts, or moves
  closer/farther from the camera. The thumb gets a second signal
  (abduction angle relative to the palm's own axis) because its motion
  is a CMC-joint rotation, not a simple hinge like the other fingers.
- **Screenshot vs. camera snapshot**: the spec's "Snap → Take Screenshot"
  action and its separate "Camera Snapshot" feature are the same
  underlying capability here — saving the current annotated camera
  frame — rather than two overlapping implementations (one of them a
  full-desktop screenshot, which is a bigger permission surface for no
  added benefit in this context).
- **Mock backend**: a clearly-labeled, non-ML backend that generates one
  animated synthetic hand. It exists for headless testing and so the
  full UI/pipeline can be exercised before the real model is downloaded
  — the UI shows a persistent "MOCK BACKEND — not real tracking" banner
  whenever it's active, and it's never the default.

## Installation

Requires Python 3.10+.

```bash
git clone <this-repo>
cd hand_gesture_control
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/download_models.py   # one-time, needs internet, ~7-8MB
```

`pyautogui` (keyboard/media-key actions) and, on Windows, `pycaw` +
`comtypes` (system volume) are optional — the app runs fully without
them; the specific actions that depend on them just stay disabled with a
logged reason.

## Running

```bash
python main.py
```

On first launch the app requests camera access — grant it (macOS/Windows
will prompt via the OS; Linux typically doesn't need to). If the model
file from `scripts/download_models.py` isn't found, you'll get a clear
in-app error message rather than a crash, with instructions.

Want to see the full UI without a real camera or a downloaded model?
Switch **Settings → Detection → Backend** to `mock` — it drives the
whole pipeline with one animated synthetic hand.

## Configuration

Everything in Settings is live — no restart, no "Apply" button — and
persists to a per-user config directory (not inside the repo):

- Linux: `~/.config/hand_gesture_control/settings.json`
- Windows: `%APPDATA%\hand_gesture_control\settings.json`
- macOS: `~/.config/hand_gesture_control/settings.json`

See `configs/README.md` for details and `app/config/schema.py` for every
available field (camera, detection, smoothing, visualization, gesture
thresholds, pinch-volume, performance).

## Performance

Real numbers, not claims — run the benchmark yourself:

```bash
python scripts/benchmark.py --seconds 15                 # live camera
python scripts/benchmark.py --backend mock --seconds 10  # no camera needed
```

Reports average/min/max frame time, average detection latency, FPS, and
dropped frames. The in-app performance overlay (Settings → Performance)
shows the same metrics live, computed by the same `PerfMonitor`.

## Testing

```bash
pip install -r requirements.txt
pytest
```

67 tests, all exercising real logic against procedurally-generated
synthetic hand poses (`app/utils/synthetic_hand.py`) — no camera, GPU, or
downloaded model required. Covers geometry math, finger-state
classification (including the thumb's special-cased logic), every static
gesture, dynamic gesture detection, the multi-hand tracker's identity
stability and occlusion tolerance, One Euro Filter smoothing behavior,
pinch-volume mapping, snap-detector temporal logic and cooldown, the
gesture engine's confirmation/debounce state machine, the action
registry and mapping dispatcher, and config load/save (including
recovery from a corrupted settings file).

## Known limitations

Documented honestly rather than hidden:

- **No recording**: "Start/Stop Recording" is wired into the action
  registry and settable in the mapping table, but its implementation is
  a stub (surfaces a toast saying so) rather than a working feature —
  isolated behind the same interface so a real implementation can be
  dropped in later without touching anything else.
- **No custom-gesture recording UI**: the gesture engine's temporal
  window (`app/gestures/dynamic_gestures.py`) and event history
  (`GestureEngine.history`) are architected to support recording and
  matching a custom motion sequence later, but that UI isn't built.
- **Interaction zones, cursor control, air-click, and two-hand
  gestures** (zoom/rotate/scale) from the original feature wishlist are
  not implemented. The per-hand tracking, motion history, and geometry
  this would build on all exist and are exercised by other features
  (e.g. dynamic-gesture detection already tracks per-hand velocity),
  so adding them is additive, not a re-architecture.
- **Volume reading on Linux/macOS**: setting volume works via `pactl` /
  `amixer` / `osascript`; *reading back* the current system volume
  reliably across every Linux audio setup is brittle enough that
  `get_volume_percent()` intentionally returns `None` rather than a
  guess in the cases it can't verify — callers fall back to a sane
  default instead of trusting a made-up number.
- **Camera enumeration** probes device indices 0–5 and reports which
  ones open; OpenCV has no reliable cross-platform "list devices with
  real names" API without a heavier platform-specific dependency, so
  devices are labeled generically ("Camera 0", "Camera 1", ...).

## Roadmap

- Custom gesture recording (record a short landmark sequence, match
  similar sequences later) — architecture is in place, UI is not.
- Interaction zones and cursor/air-click control mode.
- Two-hand gestures (pinch-zoom, rotate, scale).
- A second detector backend (e.g. an ONNX-exported model) to exercise
  the backend-swap path with a real second implementation, not just the
  mock.
- Session recording with overlays baked in.

## Privacy

Camera frames are processed entirely on-device. Nothing is uploaded or
transmitted anywhere, and no cloud service is required for any core
feature. The camera preview shows a persistent "Camera active" indicator
whenever the camera is live.

## License

MIT — see [LICENSE](LICENSE).
