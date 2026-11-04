import unittest

from breaktail_bus import ActionRequest, ActionResult, EventBus, Observation


class EventBusTests(unittest.TestCase):
    def test_observation_is_published(self):
        bus = EventBus()
        seen = []
        bus.subscribe("observation", seen.append)
        event = Observation(source="test_sensor", capability="screen.observe", confidence=0.9,
                            payload={"text": "visible"}, provenance={"origin": "mock"})
        bus.publish(event)
        self.assertEqual(seen, [event])
        self.assertEqual(bus.history(), (event,))

    def test_request_produces_correlated_result(self):
        bus = EventBus()
        bus.register_action_handler(
            "memory.search",
            lambda request: ActionResult(source="mock_memory", capability=request.capability,
                                         trace_id=request.trace_id, success=True,
                                         payload={"matches": []}, evidence=[{"kind": "mock"}]),
        )
        result = bus.request(ActionRequest(source="breaktail", capability="memory.search", payload={"query": "x"}))
        self.assertTrue(result.success)
        self.assertEqual(result.evidence, [{"kind": "mock"}])
        self.assertEqual([event.kind for event in bus.history()], ["action_request", "action_result"])

    def test_unhandled_request_is_explicit_failure(self):
        result = EventBus().request(ActionRequest(source="breaktail", capability="screen.observe"))
        self.assertFalse(result.success)
        self.assertIn("no action handler", result.error)


if __name__ == "__main__":
    unittest.main()
