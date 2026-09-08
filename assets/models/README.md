# Models

This folder is where the MediaPipe HandLandmarker model file lives at
runtime (`hand_landmarker.task`, ~7-8MB). It isn't committed to the
repository -- run this once with an internet connection:

```
python scripts/download_models.py
```

That downloads the model here. If you'd rather place it somewhere else,
point `Settings > Detection > Model Path` (or `detection.model_path` in
your config file) at wherever you put it.
