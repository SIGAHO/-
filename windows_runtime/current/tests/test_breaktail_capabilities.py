import unittest

from breaktail_bus import ActionRequest
from breaktail_capabilities import CapabilityAlreadyRegisteredError, CapabilityNotFoundError, CapabilityRegistry
from adapters.fio_adapter import FioAdapter
from adapters.luculia_adapter import LuculiaAdapter


class CapabilityRegistryTests(unittest.TestCase):
    def test_register_resolve_and_list(self):
        registry = CapabilityRegistry()
        provider = object()
        registry.register("memory.search", provider)
        self.assertIs(registry.resolve("memory.search"), provider)
        self.assertEqual(registry.list_capabilities(), ("memory.search",))

    def test_duplicate_and_missing_capability_are_explicit(self):
        registry = CapabilityRegistry()
        registry.register("memory.search", object())
        with self.assertRaises(CapabilityAlreadyRegisteredError):
            registry.register("memory.search", object())
        with self.assertRaises(CapabilityNotFoundError):
            registry.resolve("not.real")

    def test_reference_adapters_start_disconnected_and_mock_can_verify_capability(self):
        registry = CapabilityRegistry()
        fio = FioAdapter()
        luculia = LuculiaAdapter()
        self.assertEqual(fio.capabilities(), ())
        self.assertEqual(luculia.capabilities(), ())
        fio.register_verified("memory.search", lambda request: {"query": request.payload["query"], "matches": []}, registry)
        self.assertIs(registry.resolve("memory.search"), fio)
        result = fio.handle(ActionRequest(source="test", capability="memory.search", payload={"query": "hello"}))
        self.assertTrue(result.success)
        self.assertEqual(result.payload["query"], "hello")


if __name__ == "__main__":
    unittest.main()
