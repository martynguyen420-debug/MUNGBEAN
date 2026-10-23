import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

path = Path(__file__).resolve().parents[1] / 'start-two-ports.py'
spec = importlib.util.spec_from_file_location('ports', path)
ports = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ports)
FLAGS = '--listen --port --user-directory --input-directory --output-directory --temp-directory --database-url'


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'COMFY_ROOT': str(root), 'COMFY_INSTANCE_8188': str(root / 'a'), 'COMFY_INSTANCE_8189': str(root / 'b')})
        self.env.start()
        self.help = patch.object(ports.subprocess, 'run', return_value=Mock(returncode=0, stdout=FLAGS))
        self.help.start()

    def tearDown(self):
        self.help.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_preserves_both_running(self):
        with patch.object(ports, 'healthy', return_value=True), patch.object(ports.subprocess, 'Popen') as spawn:
            self.assertEqual(ports.main(), 0)
            spawn.assert_not_called()

    def test_occupied_unhealthy_not_replaced(self):
        with patch.object(ports, 'healthy', return_value=False), patch.object(ports, 'available', return_value=False), patch.object(ports.subprocess, 'Popen') as spawn:
            self.assertEqual(ports.main(), 1)
            spawn.assert_not_called()

    def test_starts_two_with_distinct_directories(self):
        with patch.object(ports, 'healthy', side_effect=[False, False, True, True]), patch.object(ports, 'available', return_value=True), patch.object(ports.subprocess, 'Popen') as spawn:
            spawn.return_value.pid = 123
            self.assertEqual(ports.main(), 0)
            self.assertEqual(spawn.call_count, 2)
            first, second = [c.args[0] for c in spawn.call_args_list]
            self.assertEqual(first[first.index('--port') + 1], '8188')
            self.assertEqual(second[second.index('--port') + 1], '8189')
            self.assertNotEqual(first[first.index('--user-directory') + 1], second[second.index('--user-directory') + 1])

    def test_only_missing_port_started(self):
        with patch.object(ports, 'healthy', side_effect=[True, False, True]), patch.object(ports, 'available', return_value=True), patch.object(ports.subprocess, 'Popen') as spawn:
            spawn.return_value.pid = 123
            self.assertEqual(ports.main(), 0)
            spawn.assert_called_once()
            args = spawn.call_args.args[0]
            self.assertEqual(args[args.index('--port') + 1], '8189')


if __name__ == '__main__':
    unittest.main()
