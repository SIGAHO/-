import unittest

from breaktail_body import BreaktailBody
from breaktail_bus import ActionResult, Observation
from breaktail_capabilities import CapabilityRegistry


def observation(capability, payload, **kwargs):
    return Observation(source="test_sensor", capability=capability, payload=payload,
                       provenance={"kind": "test"}, **kwargs)


class BodyTests(unittest.TestCase):
    def test_push_state_is_compressed_and_dnd_suppresses_low_priority(self):
        body = BreaktailBody()
        body.publish(observation("system.time", {"local_time": "11:34"}))
        body.publish(observation("system.idle", {"idle_sec": 12}))
        body.publish(observation("screen.changed", {"summary": "editor shows one error"}))
        body.set_attention("coding", current_task="fix tests", do_not_disturb=True)
        body.publish(observation("notification.arrived", {"message": "marketing ping"}))
        state = body.state()
        self.assertEqual(state["time"], "11:34")
        self.assertEqual(state["idle_sec"], 12)
        self.assertEqual(state["screen_summary"], "editor shows one error")
        self.assertEqual(state["recent_events"], [])


    def test_urgent_push_is_delivered_and_unknown_screen_is_not_claimed(self):
        body = BreaktailBody()
        body.set_attention("coding", do_not_disturb=True)
        body.publish(observation("screen.changed", {}))
        body.publish(observation("task.result", {"message": "test failed", "urgent": True}))
        state = body.state()
        self.assertIsNone(state["screen_summary"])
        self.assertEqual(state["recent_events"][0]["capability"], "task.result")


    def test_pull_api_returns_failure_when_unwired_and_evidence_when_wired(self):
        registry = CapabilityRegistry()
        body = BreaktailBody(registry=registry)
        self.assertFalse(body.screen.look(reason="user asked").ok)
        def screen(request):
            return ActionResult(source="mock", capability=request.capability, trace_id=request.trace_id,
                                success=True, payload={"text": "visible error"}, evidence=[{"kind": "mock"}])
        registry.register("screen.look", screen)
        result = body.screen.look(reason="user asked")
        self.assertTrue(result.ok)
        self.assertEqual(result.payload["text"], "visible error")
        self.assertTrue(result.evidence)


if __name__ == "__main__":
    unittest.main()
