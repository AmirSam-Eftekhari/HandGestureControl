import time

from app.actions.action_registry import ActionContext, available_actions, run_action
from app.actions.mapping import ActionDispatcher
from app.config.schema import ActionMappingEntry
from app.gestures.gesture_engine import GestureEvent


def test_all_default_actions_are_registered_and_known():
    registry = available_actions()
    assert "take_screenshot" in registry
    assert "pause_resume_tracking" in registry
    assert "none" in registry


def test_run_action_calls_the_right_context_callback():
    called = []
    ctx = ActionContext(take_screenshot=lambda: called.append("screenshot"))
    assert run_action("take_screenshot", ctx) is True
    assert called == ["screenshot"]


def test_run_action_unknown_id_returns_false_and_does_not_raise():
    ctx = ActionContext()
    assert run_action("totally_made_up_action", ctx) is False


def test_run_action_swallows_exceptions_from_the_callback():
    def boom():
        raise RuntimeError("nope")

    ctx = ActionContext(take_screenshot=boom)
    assert run_action("take_screenshot", ctx) is False  # logged, not raised


def _event(gesture_id="snap", hand_id=1):
    return GestureEvent(
        gesture_id=gesture_id, hand_id=hand_id, handedness="Right", confidence=1.0, timestamp_ms=0.0, kind="snap"
    )


def test_dispatcher_runs_enabled_mapping_for_matching_gesture():
    calls = []
    ctx = ActionContext(take_screenshot=lambda: calls.append(1))
    mappings = [ActionMappingEntry(gesture_id="snap", action_id="take_screenshot", enabled=True, cooldown_ms=0.0)]
    dispatcher = ActionDispatcher(mappings, ctx)
    executed = dispatcher.handle_event(_event())
    assert executed == ["take_screenshot"]
    assert calls == [1]


def test_dispatcher_skips_disabled_mapping():
    calls = []
    ctx = ActionContext(take_screenshot=lambda: calls.append(1))
    mappings = [ActionMappingEntry(gesture_id="snap", action_id="take_screenshot", enabled=False)]
    dispatcher = ActionDispatcher(mappings, ctx)
    executed = dispatcher.handle_event(_event())
    assert executed == []
    assert calls == []


def test_dispatcher_respects_per_mapping_cooldown():
    calls = []
    ctx = ActionContext(take_screenshot=lambda: calls.append(1))
    mappings = [ActionMappingEntry(gesture_id="snap", action_id="take_screenshot", enabled=True, cooldown_ms=1000.0)]
    dispatcher = ActionDispatcher(mappings, ctx)

    dispatcher.handle_event(_event())
    dispatcher.handle_event(_event())  # immediately again, should be blocked
    assert calls == [1]


def test_dispatcher_never_treats_control_volume_as_a_discrete_action():
    calls = []
    ctx = ActionContext(notify=lambda msg: calls.append(msg))
    mappings = [ActionMappingEntry(gesture_id="pinch", action_id="control_volume", enabled=True)]
    dispatcher = ActionDispatcher(mappings, ctx)
    executed = dispatcher.handle_event(_event(gesture_id="pinch"))
    assert executed == []


def test_pinch_volume_enabled_reflects_mapping_state():
    ctx = ActionContext()
    mappings = [ActionMappingEntry(gesture_id="pinch", action_id="control_volume", enabled=True)]
    dispatcher = ActionDispatcher(mappings, ctx)
    assert dispatcher.pinch_volume_enabled() is True

    mappings[0].enabled = False
    dispatcher.configure(mappings)
    assert dispatcher.pinch_volume_enabled() is False
