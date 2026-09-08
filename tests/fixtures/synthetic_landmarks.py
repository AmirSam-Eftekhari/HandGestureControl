"""Re-exports the synthetic hand generator for test use.

The actual implementation lives in ``app/utils/synthetic_hand.py`` since
it's also used at runtime by ``app.vision.mock_backend`` -- see that
module's docstring for why. This module just keeps the familiar
``tests.fixtures.synthetic_landmarks`` import path working for the test
suite.
"""

from app.utils.synthetic_hand import (  # noqa: F401
    build_synthetic_hand,
    fist,
    four_fingers,
    ok_sign,
    open_palm,
    peace_sign,
    pinch_pose,
    pointing,
    three_fingers,
    thumb_down,
    thumb_up,
)
