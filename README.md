# Hand Gesture Control

A real-time hand tracking and gesture control desktop application: two
hands, 21 landmarks each, robust finger-state analysis, static gesture
recognition (built-in and your own recorded gestures), a continuous
pinch-to-volume mode, and a fully configurable gesture-to-action mapping
system — all running locally, with a custom-designed PySide6 interface
and a packaged Windows build that needs no Python installation to run.

![status](https://img.shields.io/badge/status-active-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

---

## What this is

A full application, not a webcam loop with MediaPipe's default drawing
utilities on top: a layered architecture that separates camera I/O,
detection, tracking, geometry, gesture recognition, action dispatch, and
rendering into independently testable modules; a real-time pipeline that
never blocks the UI and always processes the newest available frame;
proper cross-thread safety throughout (every worker-thread-to-GUI-thread
handoff goes through Qt's queued signal mechanism or an equivalent
mutex-guarded handoff, never a direct cross-thread call); and a
hand-built design system instead of default Qt widgets.

It's built to be **extended**, not just run: swap in a different
detector backend, add a new built-in static gesture, wire a gesture to
a new system action, or add a new visualization mode — each of those is
a localized change, not a rewrite. (Adding a gesture *without* touching
code at all is a built-in feature now too — see "Recording your own
gesture" below.)

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
- **Record your own gestures**: hold a pose, capture it, name it, assign
  it any action. Matching is hand- and mirror-agnostic by construction
  (see "Recording your own gesture" below) — record with either hand,
  recognized with both.
- **Finger-snap detection** using closing velocity + a temporal window +
  cooldown, distinguishing an intentional snap from fingers merely
  resting close together.
- **Pinch-to-volume mode**: thumb-index distance, normalized by hand
  scale, EMA-smoothed, with a dead zone to prevent jittery oscillation.
- **Configurable gesture → action mapping** with per-mapping enable
  toggle, cooldown, and a live editor UI. Nothing disruptive (media keys,
  volume, keyboard shortcuts) is enabled by default. Detection settings
  (backend, model, GPU, confidence thresholds) can be changed live too,
  without restarting the app.
- **Temporal smoothing** via a One Euro Filter, applied to *both* the
  on-screen (image-space) and metric (world-space) landmarks
  independently per tracked hand — see "Notable bugs found and fixed"
  below for why that distinction matters.
- **Animated hand-status panel**: two stylized hand glyphs whose five
  fingers individually highlight in real time as your fingers extend and
  fold.
- **Measured performance**, not claimed performance: live FPS, frame
  time, and detection latency (UI updates at a throttled 10Hz so reading
  the numbers doesn't itself cost frame budget), plus a standalone
  `scripts/benchmark.py`.
- **Local-first and private**: camera frames never leave the machine;
  no cloud service is required for any core feature.
- **Backend-swappable by design**: every module above the detector talks
  to a backend-agnostic `HandObservation`/`FrameResult` model, not
  MediaPipe types directly.
- **Packaged as a real Windows app**: a PyInstaller build produces a
  folder you can double-click `HandGestureControl.exe` from, with no
  Python, VS Code, or terminal required to run it.

## Supported gestures

| Type    | Gesture                                   |
|---------|--------------------------------------------|
| Static  | Open palm, fist, pointing, thumb up, thumb down, peace/V, OK, pinch, three fingers, four fingers |
| Special | Finger snap, pinch-and-hold (continuous volume control) |
| Custom  | Whatever you record yourself — see below |

Default gesture → action mappings (edit anytime in **Mapping**):

| Gesture     | Action                          | Enabled by default |
|-------------|----------------------------------|---------------------|
| Pinch       | Continuous volume control        | ✅ |
| Snap        | Take camera snapshot             | ✅ |
| Open palm   | Pause / resume tracking          | ✅ |
| Fist        | Cancel current mode               | off |
| Thumb up / down | Confirm / Cancel (log only)  | off |
| Peace       | Toggle skeleton overlay           | off |

Earlier versions also shipped built-in dynamic (motion) gestures --
swipe, wave, circular motion. They were removed rather than kept
alongside custom gestures: this app's custom-gesture system is
pose-based (see below), so a fixed built-in *motion* gesture the user
couldn't redefine the same way everything else now can be didn't earn
its place. If you want a swipe-like trigger, the practical equivalent
today is recording a distinct pose (e.g. an open hand held sideways) as
a custom gesture.

### Recording your own gesture

**Mapping → Record New Gesture** opens a small recorder: hold a pose in
front of the camera, click **Capture** (it samples for ~0.7s and
averages the readings, which is more robust than trusting a single
frame), name it, and assign one of the existing actions to it — media
controls, volume step, mute, screenshot, mirror/skeleton toggles,
keyboard shortcuts, anything in the Action dropdown except continuous
volume control (that one's pinch-only, since it needs a continuously
*varying* distance, not a fixed pose). The new gesture shows up in the
mapping table immediately, right alongside the built-in ones, and can be
enabled/disabled, re-cooled-down, or deleted the same way.

Recording is deliberately **pose-based, not motion-based** — a template
is a snapshot of finger curl and thumb geometry, not a recorded
trajectory. This is what makes matching simple, fast, and (per the
project's testing philosophy) verifiable with synthetic data instead of
needing trajectory-matching (DTW-style) machinery that would be a
meaningfully bigger, riskier thing to get right.

**Works with either hand, regardless of which one you recorded with, and
regardless of Camera Mirror Mode.** This isn't a claim to just take on
faith — it follows from *what* gets stored: a template holds finger curl
ratios, a thumb angle, and a normalized pinch distance, never raw x/y
position. A folded finger produces the same curl value whether it's the
left or right hand, and mirroring changes *where* a hand appears on
screen, not *how folded its fingers are*. See
`app/gestures/custom_gestures.py` for the full reasoning, including why
this project deliberately avoids trying to "correct" handedness labels
based on the mirror setting rather than sidestepping the question
entirely.

## Architecture

```
Camera Capture (own thread)
        │  (always-newest-frame handoff, no queue)
        ▼
Frame Pipeline (own thread)
        │
        ├─ Hand Detector Backend  (MediaPipe Tasks HandLandmarker, swappable)
        ├─ Multi-Hand Tracker     (stable IDs, occlusion tolerance, NaN/Inf backstop)
        ├─ Landmark Smoother      (One Euro Filter, image- AND world-space, per hand)
        ├─ Geometry Engine        (palm scale/axes, finger straightness, angles)
        ├─ Finger-State Classifier
        ├─ Gesture Engine         (static + custom-gesture matching, confirmation, snap, cooldown)
        ├─ Action Dispatcher      (gesture → action mapping, its own cooldown)
        ├─ Pinch-Volume Controller (commits to the OS only when the value actually changes)
        └─ Overlay Renderer       (draws skeleton/labels/trail onto the frame)
        │
        ▼
Qt queued signal → Main Window (GUI thread: camera view, hand-status
                    panel, status bar, toasts, settings, gesture mapping)
```

```
app/
├── main_window.py          # integration point: owns camera + pipeline, wires the UI
├── camera/                 # threaded camera capture, bounded/async enumeration, backoff reconnect
├── vision/                 # backend interface + MediaPipe/mock implementations,
│                            #   landmark model, geometry, finger-state, smoothing, path resolution
├── tracking/                # multi-hand identity + motion history + NaN backstop
├── gestures/                # static + custom-gesture classifiers, snap, pinch, gesture engine
├── actions/                  # action registry, gesture→action mapping, system actions
├── pipeline/                 # the real-time frame-processing worker/thread
├── ui/                       # design system, widgets, camera view, settings, mapping screen
├── config/                   # typed config schema, validation/clamping, defaults, JSON persistence
└── utils/                    # perf monitor, logging, errors, path resolution, cross-thread dispatch primitives
tests/                        # pytest suite, synthetic-landmark fixtures, hardening regression tests
scripts/                      # model downloader, benchmark mode, icon generator
```

## Cross-thread safety

This is worth calling out explicitly because it was the source of the
most serious bugs found during a hardening pass (see below). The rule
followed everywhere in this codebase:

- **Qt signal, queued connection** — for anything targeting a `QObject`
  that lives on a thread *which runs a Qt event loop* (the GUI thread).
  `CameraManager`/`FramePipeline` re-emit their worker's signals as their
  own, so the double-hop always lands safely on the GUI thread.
- **`GuiInvoker` (`app/utils/gui_invoker.py`)** — for arbitrary callables
  that need to run on the GUI thread but don't have a natural Qt signal
  of their own (this is how `ActionContext` callbacks that touch
  `QWidget` state — mirror toggle, screenshot, toast notifications — are
  dispatched from the pipeline's worker thread).
- **Mutex-guarded "pending state, applied by the owning thread"** — for
  the camera and pipeline worker loops themselves, which run a
  hand-rolled `while` loop rather than `QThread.exec()` (so they have
  full control over frame timing) — which means a plain queued signal
  targeting *them* would never actually be delivered, since nothing
  pumps their event queue. Device switching and live config
  reconfiguration both use this pattern.
- **`BackgroundExecutor` (`app/utils/background_executor.py`)** — for
  blocking system calls (OS volume via subprocess, simulated media
  keys) that must block neither the GUI thread nor the realtime pipeline
  thread.

## Design decisions worth knowing about

- **Detection backend**: [MediaPipe Tasks `HandLandmarker`](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker),
  run in `VIDEO` mode. Timestamps handed to MediaPipe are generated
  internally by the backend itself (a monotonic clock, floored against
  "strictly greater than the last value used", lock-protected) rather
  than trusted from the caller — this guarantees MediaPipe's "timestamp
  must be monotonically increasing" invariant regardless of frame
  timing, duplicate captures, or reconnects. GPU delegate is tried first
  and falls back to CPU automatically if unavailable, and that fallback
  is cached for the process so a known-unsupported GPU configuration
  isn't retried on every reinitialization.
- **Frame handling**: neither the camera thread nor the pipeline thread
  queues frames. Each always holds only the *newest* one; if a consumer
  falls behind, older frames are dropped.
- **Resource path resolution** (`app/utils/paths.py`): bundled resources
  (the model file, the icon) are resolved relative to the application's
  own location — the PyInstaller bundle root when frozen, the project
  root when running from source — never the process's current working
  directory. Verified against a real PyInstaller-built executable
  (launched from an arbitrary working directory), not just simulated.
- **Camera enumeration**: bounded (probes a capped range of indices,
  stopping early once it's found at least one real device and then hit
  several consecutive failures in a row) and runs off the GUI thread.
  The configured device index is validated against what's actually
  available at startup, with an automatic, clearly-notified fallback
  rather than repeatedly trying to open a camera that doesn't exist.
- **Camera reconnect**: bounded exponential backoff (0.5s up to an 8s
  cap), not a fixed retry-forever loop — and the backoff sleep is
  interruptible, so shutting down or switching cameras doesn't have to
  wait out a multi-second delay.
- **Config validation**: every field loaded from `settings.json` is
  clamped into a sane range at load time (`app/config/schema.py:
  validate_and_clamp`) — out-of-range thresholds, inverted min/max
  pairs, `NaN`, unknown enum-like strings, and non-numeric garbage all
  resolve to a safe default rather than propagating into the app. A
  `schema_version` field and a (currently a documented no-op, since
  there's only been one schema so far) migration hook exist so a future
  breaking schema change has an obvious place to add a real migration.
- **Screenshot vs. camera snapshot**: the "Snap → Take Screenshot"
  action and the "Camera Snapshot" feature are the same underlying
  capability here — saving the current annotated camera frame — rather
  than two overlapping implementations.
- **Mock backend**: a clearly-labeled, non-ML backend that generates one
  animated synthetic hand, for headless testing and for exercising the
  full UI/pipeline without a downloaded model. The UI shows a persistent
  "MOCK BACKEND — not real tracking" banner whenever it's active.

## Notable bugs found and fixed during a hardening pass

Kept here rather than only in commit history, since a couple of these
are the kind of thing worth knowing about if you're extending this
codebase:

- **MediaPipe timestamp crash** (`ValueError: Input timestamp must be
  monotonically increasing`) — root cause was integer-millisecond
  truncation collisions at high frame rates (two frames landing in the
  same millisecond both round down to the same integer), with no
  protection against reconnects or concurrent access either. Fixed by
  enforcing strict monotonicity **at the backend boundary**, independent
  of whatever timestamp the caller supplies.
- **`QObject::setParent: Cannot set parent, new parent is in a different
  thread`** — the actual root cause was more serious than the warning
  suggests: `ActionContext` callbacks (mirror toggle, screenshot, toast
  notifications) are bound `MainWindow` methods that mutate `QWidget`
  state, but were being invoked directly from `ActionDispatcher` inside
  `PipelineWorker._process()` — i.e. on the pipeline's worker thread,
  not the GUI thread. That's a genuine crash risk, not a cosmetic
  warning. Fixed with `GuiInvoker` (see "Cross-thread safety" above).
- **Smoothing silently had no effect on gesture recognition** — the
  landmark smoother only filtered `hand.landmarks` (normalized
  image-space coordinates), but `compute_geometry()` prefers
  `hand.world_landmarks` (metric coordinates) whenever a backend
  provides them — which the real MediaPipe backend always does. So all
  of the One Euro Filter's jitter reduction was applied to a data path
  that finger-state classification and gesture recognition never
  actually read. Fixed by smoothing both landmark sets independently
  (they live on very different amplitude scales, so they need separate
  filter *state*, even though the same cutoff/beta configuration
  reasonably applies to both).
- **A camera device switch could race with the capture loop** — an
  earlier version called `CameraWorker._release()` directly from the
  caller's thread while the capture loop could simultaneously be
  mid-`read()` on the same `cv2.VideoCapture` object on the camera
  thread. Fixed with a generation-counter handoff: callers only ever
  request a change; the capture loop applies it on its own thread.
- **`apply_config()` raced the pipeline's own frame loop** — calling a
  method directly on the pipeline worker from the GUI thread while the
  worker thread could be mid-frame reading the same config object. Fixed
  with the same mutex-guarded pending-value pattern (see "Cross-thread
  safety").
- **Changing the detection backend in Settings did nothing** — the
  dropdown existed and could be changed, but `apply_config()` never
  actually reinitialized the detector. Fixed with live backend
  reinitialization that falls back to the previous working backend if
  the new one fails to start, rather than leaving hand tracking dead.
- **Pinch-volume mode issued a system volume call on every single
  frame** it was active, regardless of whether the value had actually
  changed — needless subprocess-spawn overhead on the realtime pipeline
  thread's critical path. Fixed to only call out on an actual change.
- **Camera enumeration blocked the GUI thread** during startup and every
  camera switch (each probed index can take tens to hundreds of ms).
  Fixed with async enumeration + `GuiInvoker` to marshal the result back.
- **Blind, unbounded camera-index probing** — the app was observed
  attempting to open camera indices that didn't exist, indefinitely.
  Enumeration is now bounded and stops early past the last real device;
  a configured-but-unavailable index falls back automatically instead of
  retrying forever.
- **Model path resolved against the process's working directory** —
  broke depending on how the app was launched (a different terminal
  directory, an IDE's own default cwd, a shortcut). Fixed with
  `app/utils/paths.py`, which resolves bundled resources against the
  application's own location instead — verified against a real
  PyInstaller-built executable launched from an unrelated directory.
- **`QFont::setPointSize: Point size <= 0 (-1)`** — Qt's style engine
  can end up copying/deriving fonts with an invalid point size when the
  application never establishes an explicit one. Fixed by setting an
  explicit, valid application-wide font in `main.py`.
- **A single bad frame could silently kill the pipeline thread** — there
  was no outer exception guard around per-frame processing; an
  unexpected error (malformed data, an edge case in geometry math) would
  propagate out of the worker's `while` loop and end it, freezing hand
  tracking with no visible error and no recovery. Fixed with per-hand
  and per-frame exception containment, rate-limited logging, and a
  degrade-to-"skip this frame" behavior throughout.
- **Volume control did nothing on Windows** — the root cause was a
  classic COM apartment-threading violation: the Windows audio endpoint
  (a COM interface pointer, via `pycaw`) was activated once in
  `SystemVolumeController.__init__()`, which runs on the GUI thread, and
  cached. Actual volume calls run on `BackgroundExecutor`'s dedicated
  worker thread (specifically so they never block the GUI or realtime
  pipeline threads) — a *different* OS thread that never initialized COM
  for itself. Calling a COM method with a pointer that belongs to a
  different thread's apartment is undefined/silently-failing behavior on
  Windows. Fixed so every thread that actually issues a volume command
  activates and caches *its own* endpoint in thread-local storage, after
  calling `CoInitialize()` on itself first — see
  `app/actions/system_actions.py` for the full explanation. Also added:
  the Pinch Volume toggle now tells you plainly (a toast, not silence) if
  no working volume backend was found, and the Windows build now bundles
  `pycaw`/`comtypes` explicitly rather than trusting PyInstaller's
  default import analysis to catch a library that does some of its own
  dynamic module setup.

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

## Running from source

```bash
python main.py
```

On first launch the app requests camera access — grant it (macOS/Windows
will prompt via the OS; Linux typically doesn't need to). If the model
file from `scripts/download_models.py` isn't found, you'll get a clear
in-app error message with the exact path it looked at, rather than a
crash.

Want to see the full UI without a real camera or a downloaded model?
Switch **Settings → Detection → Backend** to `mock` — it drives the
whole pipeline with one animated synthetic hand.

## Building the Windows application

```
build_windows.bat
```

Run from a plain Command Prompt in the project root (not from inside an
IDE). This creates an isolated build virtual environment, installs
dependencies, downloads the model if it isn't present yet, generates the
app icon, and runs PyInstaller. Output:

```
dist\HandGestureControl\HandGestureControl.exe
```

Double-click it, or run `make_release_zip.bat` afterward to produce
`release\HandGestureControl.zip` — a single file that can be extracted
on another Windows machine with no Python installed and run directly.

**Why a folder, not a single .exe file:** a PyInstaller "onefile" build
re-extracts its entire contents into a temp directory on every launch.
For an app bundling MediaPipe, OpenCV, and Qt, that means several extra
seconds on *every single startup* for no real benefit — this app isn't
distributed as an email attachment where "just one file" matters, and
the zipped folder is just as easy to share. See `HandGestureControl.spec`
for the full reasoning.

**What's actually been verified vs. what hasn't:** this build was
produced and smoke-tested in this project's Linux development sandbox
(a real PyInstaller build, not a simulation — confirming the import
graph resolves, required data files get bundled, and the packaged
executable actually launches and correctly resolves the frozen-mode
resource paths). That is *not* the same as testing the actual `.exe` on
Windows, which needs a Windows machine to build and run — PyInstaller
does not cross-compile. Native DLL loading specifics, the embedded icon,
actual camera access through Windows' capture backends, and the
`pycaw`-based volume control path are unverified until someone runs
`build_windows.bat` on a real Windows machine. If something doesn't work
there, `dist\HandGestureControl\_internal\` and the log file (see
"Troubleshooting") are the first places to look.

## Model handling

The `.task` model file (~7-8MB) isn't committed to the repository — see
`scripts/download_models.py`. It's bundled automatically into the
Windows build if present in `assets/models/` at build time.

## Camera selection

**Settings → Camera → Camera device** lists what was found on this
machine (enumeration runs in the background so it never blocks the UI).
The toolbar's camera-switch icon cycles through available devices. If
the configured camera isn't available at startup (unplugged, index
shifted), the app automatically falls back to the first available one
and shows a toast explaining why.

## Optional Windows actions

Keyboard shortcuts and media-key simulation need `pyautogui`; system
volume control on Windows needs `pycaw` + `comtypes`. All three are in
`requirements.txt`; if any is missing or fails to initialize (no
display, no supported audio endpoint, etc.), the specific actions that
depend on it are disabled with a logged reason — nothing else in the app
is affected.

## Configuration

Everything in Settings is live — no restart, no "Apply" button — and
persists to a per-user config directory (not inside the repo):

- Windows: `%APPDATA%\hand_gesture_control\settings.json`
- Linux: `~/.config/hand_gesture_control/settings.json`
- macOS: `~/.config/hand_gesture_control/settings.json`

Every field is validated and clamped into a safe range at load time —
see `app/config/schema.py: validate_and_clamp` — so a corrupted or
hand-edited settings file can't destabilize the app; anything it can't
make sense of falls back to a factory default rather than being
rejected wholesale. Your recorded custom gestures live alongside it, in
their own `custom_gestures.json` (kept separate from `settings.json`
since they're closer to your own content than an app setting — see
`app/config/custom_gestures_store.py`), with the same
corrupted-entry-tolerant loading. Logs live alongside both, under
`logs/app.log` (rotated, capped size). See `configs/README.md` for
details and `app/config/schema.py` for every available setting field.

## Performance

Real numbers, not claims — run the benchmark yourself:

```bash
python scripts/benchmark.py --seconds 15                 # live camera
python scripts/benchmark.py --backend mock --seconds 10  # no camera needed
```

Reports average/min/max frame time, average detection latency, FPS, and
dropped frames. The in-app performance overlay (Settings → Performance)
shows the same metrics, refreshed at a throttled 10Hz — the pipeline
itself still measures every frame; only the on-screen text updates are
rate-limited, since redrawing a number 60 times a second is wasted GUI
work a person can't perceive anyway.

### Getting the best performance (and the best tracking accuracy)

Roughly in order of how much difference each one tends to make:

1. **Enable GPU acceleration** (Settings → Detection → GPU acceleration).
   MediaPipe's GPU delegate is meaningfully faster than CPU when it's
   available. If your machine doesn't support it, the app already falls
   back to CPU automatically and won't keep retrying GPU init on every
   restart of detection — you'll see this in the log
   (`app.vision.mediapipe_backend`) rather than a repeated stall.
2. **Use good, even lighting, and keep your hand a reasonable distance
   from the camera** (roughly forearm's length). This is the single
   biggest lever on actual detection *quality* — MediaPipe's hand model,
   like most vision models, degrades under motion blur, backlighting, or
   a hand that's too close/too far/too far to one side of the frame.
   Fast hand motion is the other big source of missed detections; the
   temporal smoothing (One Euro Filter) helps with jitter once a hand
   *is* detected, but it can't invent a detection MediaPipe never made.
3. **Lower the camera resolution** if you don't need 1080p (Settings →
   Camera → Resolution). 1280x720 is a solid default; going to 1920x1080
   increases per-frame detection cost for very little accuracy gain in
   most setups, since MediaPipe internally works on a much smaller
   crop anyway.
4. **Set Max Hands to 1** (Settings → Detection) if you only ever use one
   hand — detecting two hands costs meaningfully more than one, for a
   feature you're not using.
5. **Turn off Motion Trail** (Settings → Visualization) and use
   **Skeleton** or **Minimal** visualization mode rather than **Detailed**
   or **Debug** — these only affect rendering cost, not detection, but
   rendering is still real per-frame work.
6. **Close other applications using the camera.** Most webcam drivers
   only support one consumer at a time cleanly; a second app holding the
   camera open is a common cause of a camera that "won't connect" as
   well as of degraded frame rate from whichever app got the connection.
7. **Increase confirmation time slightly** (Settings → Gestures →
   Confirmation time) if gestures fire when you didn't mean them to, or
   decrease it if they feel sluggish to trigger — this is a genuine
   responsiveness/reliability trade-off, not a performance one, but it's
   the setting people reach for right after "performance" so it's worth
   mentioning here.

If you're still not getting the FPS you expect after the above, run
`scripts/benchmark.py` with the real camera backend and check whether
`detection latency` or `camera read latency`-adjacent frame time is the
larger share — that tells you whether the bottleneck is MediaPipe itself
or something upstream (a slow camera driver, a busy CPU core from another
application, etc.) rather than guessing.

## Testing

```bash
pip install -r requirements.txt
pytest
```

125 tests, all exercising real logic — no camera, GPU, or downloaded
model required. Split roughly into:

- **Core vision/gesture logic** against procedurally-generated synthetic
  hand poses (`app/utils/synthetic_hand.py`): geometry math, finger-state
  classification, every static gesture, multi-hand tracking
  identity/occlusion handling, smoothing filter behavior, pinch-volume
  mapping, snap-detector temporal logic, the gesture engine's
  confirmation/debounce state machine, the action registry and mapping
  dispatcher, config load/save.
- **Custom gestures** (`tests/test_custom_gestures.py`,
  `tests/test_custom_gestures_store.py`): template building/averaging,
  distance-based matching (including an explicit test that matching is
  hand-agnostic — record with the left hand, recognize with the right),
  built-in-gestures-take-priority ordering, full confirmation/cooldown
  flow through the real `GestureEngine`, and persistence (round-trip,
  corruption recovery, malformed-entry tolerance).
- **Hardening regression tests** (`tests/test_hardening_regressions.py`):
  one test per bug found during the production-hardening pass —
  timestamp monotonicity under concurrent access, rate-limited error
  logging, bounded camera enumeration, resource path resolution in both
  normal and simulated-frozen mode, config validation/clamping against
  deliberately malformed input, the NaN/Inf backstop at the tracker
  boundary, live-detection-reinit decision logic, genuine cross-thread
  dispatch verification for `GuiInvoker` (using a real `QApplication`
  event loop, not just "didn't raise synchronously"), and the Windows
  volume-control per-thread COM activation fix (with `pycaw`/`comtypes`
  mocked, since this sandbox isn't Windows — what's under test is
  `SystemVolumeController`'s own thread-local caching logic).

Qt tests run headless automatically (`tests/conftest.py` sets
`QT_QPA_PLATFORM=offscreen`), so the suite doesn't need a display.

## Troubleshooting

- **"Hand detection model not found"** — run
  `python scripts/download_models.py`, or check
  Settings → Detection → Model Path. The error message includes the
  exact path the app looked at.
- **Camera doesn't show up** — check Settings → Camera → Camera device;
  if the list is empty, no camera was detected on any of the probed
  indices. Make sure no other application is holding the camera open.
- **"MOCK BACKEND" banner is showing** — Settings → Detection → Backend
  is set to `mock`. Switch it to `mediapipe_tasks` for real tracking.
- **Volume gestures don't do anything** — check the log
  (`logs/app.log` in the config directory above) for a line from
  `app.actions.system_actions`; it states plainly which backend it tried
  and why it's unavailable (missing `pactl`/`amixer` on Linux, missing
  `pycaw` on Windows, no supported audio endpoint, etc).
- **The app won't start (packaged build)** — check
  `dist\HandGestureControl\_internal\` exists alongside the .exe (it
  must ship together with it) and check the log file in the config
  directory above for the actual error.

## Known limitations

Documented honestly rather than hidden:

- **No recording**: "Start/Stop Recording" is wired into the action
  registry and selectable in the mapping table, but its implementation
  is a stub (shows a toast saying so) rather than a working feature.
- **Custom gestures are pose-based, not motion-based**: you can record
  and recognize a held hand *shape*, not a *motion* (a wave, a swipe
  trajectory). This is a deliberate scope decision — see "Recording your
  own gesture" above — not a partially-built feature.
- **Interaction zones, cursor control, and air-click** are not
  implemented. The per-hand tracking, motion history, and geometry this
  would build on all exist and are exercised by other features already,
  so adding them is additive.
- **Two-hand gestures** (zoom/rotate/scale using both hands together)
  are not implemented; both hands are already tracked independently
  (each with its own identity, gesture state, and custom-gesture
  matching), so this would combine existing per-hand data rather than
  needing new tracking infrastructure.
- **Handedness misclassification causes identity churn, not
  corruption**: if the detector momentarily flips its Left/Right
  classification for the same physical hand, the tracker treats it as a
  new hand (fresh id, fresh gesture/smoothing state) rather than merging
  it into the existing track, since track matching requires handedness
  to match. This never corrupts gesture *recognition* (custom and
  built-in pose matching are both hand-agnostic by construction — see
  "Recording your own gesture" above), only the continuity of the
  tracked identity itself, and only while the flicker is happening.
- **Volume reading on Linux/macOS**: setting volume works via `pactl` /
  `amixer` / `osascript`; *reading back* the current volume reliably
  across every Linux audio setup is brittle enough that
  `get_volume_percent()` intentionally returns `None` rather than a
  guess in the cases it can't verify.
- **Camera enumeration** reports generic labels ("Camera 0", "Camera
  1", ...) rather than real device names — OpenCV has no reliable
  cross-platform "list devices with names" API without a heavier
  platform-specific dependency.
- **Windows packaging is unverified on actual Windows** — see "Building
  the Windows application" above for exactly what has and hasn't been
  tested. This includes the Windows volume-control fix itself: the
  threading bug and its fix are understood and tested at the logic level
  (`tests/test_hardening_regressions.py`), but real `pycaw`/COM behavior
  on Windows hardware hasn't been observed directly.
- **Distribution size**: the Windows build is a few hundred MB, mostly
  MediaPipe's and OpenCV's compiled native libraries — both are already
  used at their minimum reasonable footprint (PySide6's is trimmed to
  only the Qt modules this app actually uses; MediaPipe and OpenCV don't
  offer the same granularity).

## Roadmap

- Motion-based custom gestures (recording a short trajectory, not just
  a pose) — the pose-based version is built; this would be a genuinely
  separate matching approach (trajectory/DTW-style), not an extension of
  the current one.
- Interaction zones and cursor/air-click control mode.
- Two-hand gestures (pinch-zoom, rotate, scale).
- A second detector backend (e.g. an ONNX-exported model) to exercise
  the backend-swap path with a real second implementation, not just the
  mock.
- Session recording with overlays baked in.
- A track-matching heuristic that tolerates a momentary handedness
  flip without losing hand identity.

## Privacy

Camera frames are processed entirely on-device. Nothing is uploaded or
transmitted anywhere, and no cloud service is required for any core
feature. The camera preview shows a persistent "Camera active" indicator
whenever the camera is live.

## License

MIT — see [LICENSE](LICENSE).
