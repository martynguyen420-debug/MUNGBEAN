import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from typing import Any, Dict, Tuple, Optional
from unittest.mock import Mock

source = ast.parse((Path(__file__).resolve().parents[1] / 'BEAVIS_FIXED.py').read_text(encoding='utf-8'))
names = {'startup_connection', 'connect_runpod_and_scan', 'comfy_alive', 'get_object_info', 'queue_status_text', 'status_text'}
code = compile(ast.Module(body=[x for x in source.body if isinstance(x, ast.FunctionDef) and x.name in names], type_ignores=[]), 'MUNG connection functions', 'exec')


class Tests(unittest.TestCase):
    def setUp(self):
        self.ns = dict(Any=Any, Dict=Dict, Tuple=Tuple, Optional=Optional,
                       COMFY_URL='', MODEL_SOURCE='remote', _object_info_cache=None,
                       SETTINGS={'comfy_url': 'https://previous-pod-8188.proxy.runpod.net', 'model_source': 'remote'},
                       requests=SimpleNamespace(get=Mock()), gr=SimpleNamespace(Error=RuntimeError),
                       save_settings_dict=Mock(), refresh_models_ui=Mock(return_value=('models',)),
                       _owned_comfy_process=None)
        exec(code, self.ns)

    def test_saved_remote_never_becomes_active(self):
        self.assertEqual(self.ns['startup_connection'](self.ns['SETTINGS']), ('', 'remote'))

    def test_local_default_unchanged(self):
        self.assertEqual(self.ns['startup_connection']({'model_source': 'local', 'comfy_url': 'https://old-pod'}), ('http://127.0.0.1:8188', 'local'))

    def test_disconnected_status_and_scan_never_call_old_url(self):
        self.assertFalse(self.ns['comfy_alive']())
        self.assertEqual(self.ns['get_object_info'](True), {})
        self.assertIn('current', self.ns['queue_status_text']())
        self.assertIn('not connected', self.ns['status_text']())
        self.ns['requests'].get.assert_not_called()

    def test_failed_candidate_does_not_replace_active_or_saved_connection(self):
        self.ns['COMFY_URL'] = 'https://working-pod'
        self.ns['_object_info_cache'] = {'working': {}}
        self.ns['requests'].get.side_effect = OSError('unreachable')
        with self.assertRaisesRegex(RuntimeError, 'connection failed'):
            self.ns['connect_runpod_and_scan']('new-pod', 'Auto', None, False)
        self.assertEqual(self.ns['COMFY_URL'], 'https://working-pod')
        self.assertEqual(self.ns['_object_info_cache'], {'working': {}})
        self.assertIn('previous-pod', self.ns['SETTINGS']['comfy_url'])
        self.ns['save_settings_dict'].assert_not_called()

    def test_success_switches_model_cache_and_saves_validated_address(self):
        payload = {'UNETLoader': {'input': {'required': {}}}}
        response = Mock()
        response.json.return_value = payload
        self.ns['requests'].get.return_value = response
        result = self.ns['connect_runpod_and_scan']('  new-pod-8188.proxy.runpod.net/ ', 'Auto', None, False)
        self.assertEqual(self.ns['COMFY_URL'], 'https://new-pod-8188.proxy.runpod.net')
        self.assertEqual(self.ns['_object_info_cache'], payload)
        self.assertEqual(self.ns['SETTINGS']['comfy_url'], self.ns['COMFY_URL'])
        self.ns['requests'].get.assert_any_call('https://new-pod-8188.proxy.runpod.net/object_info', timeout=15)
        self.ns['save_settings_dict'].assert_called_once()
        self.assertEqual(result[0], 'models')

    def test_empty_schema_does_not_save(self):
        self.ns['requests'].get.return_value.json.return_value = {}
        with self.assertRaisesRegex(RuntimeError, 'empty object_info'):
            self.ns['connect_runpod_and_scan']('https://new-pod', 'Auto', None, False)
        self.assertEqual(self.ns['COMFY_URL'], '')
        self.ns['save_settings_dict'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
