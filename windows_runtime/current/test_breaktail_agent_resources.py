from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from breaktail_agent import Workspace
from breaktail_agent_resources import observe


class ResourceObservationTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'eval/agent-unit'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_real_read_only_provider_uses_registry_without_execution_permission(self):
        (self.root/'keep.txt').write_bytes(b'keep')
        ws=Workspace(self.root,create_audit=False)
        before=set(self.root.iterdir())
        self.assertIn('observe_resources',ws.available_tools())
        self.assertNotIn('run_tests',ws.available_tools())
        result=ws.execute('observe_resources',{})
        self.assertTrue(result['read_only'])
        self.assertTrue(result['observed_at_utc'])
        self.assertEqual(result['disk']['status'],'observed')
        self.assertGreater(result['disk']['values']['total_bytes'],0)
        self.assertEqual(result['gpu']['status'],'not_connected')
        self.assertIsNone(result['gpu']['values'])
        self.assertEqual(set(self.root.iterdir()),before)
        self.assertEqual((self.root/'keep.txt').read_bytes(),b'keep')
        self.assertEqual(ws.revision,0)
        self.assertEqual(ws.changes,{})
        with self.assertRaises(ValueError):ws.execute('observe_resources',{'command':'stop'})

    def test_failed_providers_are_unknown_not_zero_and_do_not_hide_other_results(self):
        ws=Workspace(self.root,create_audit=False)
        with patch('breaktail_agent_resources.os.cpu_count',return_value=None),\
             patch('breaktail_agent_resources._windows_memory',side_effect=OSError('private detail')):
            result=observe(ws)
        self.assertEqual(result['cpu']['status'],'unavailable')
        self.assertIsNone(result['cpu']['values'])
        self.assertEqual(result['memory']['error'],'OSError')
        self.assertIsNone(result['memory']['values'])
        self.assertNotIn('private detail',str(result))
        self.assertEqual(result['disk']['status'],'observed')

    def test_unsupported_memory_and_disk_failure_are_explicit(self):
        ws=Workspace(self.root,create_audit=False)
        with patch('breaktail_agent_resources._windows_memory',side_effect=NotImplementedError()),\
             patch('breaktail_agent_resources.shutil.disk_usage',side_effect=PermissionError()):
            result=observe(ws)
        self.assertEqual(result['memory']['status'],'unsupported')
        self.assertEqual(result['disk']['status'],'unavailable')
        self.assertIsNone(result['disk']['values'])


if __name__=='__main__':unittest.main()
