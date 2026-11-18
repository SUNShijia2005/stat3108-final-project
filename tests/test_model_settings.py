"""Local model configuration; all credentials here are synthetic and no API is called."""
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app
from parcel.config import load_local_config, model_settings, save_model_settings


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '.env.local'
        self.environ = {}
        self.body = {'api_key':'test-key-only', 'model':'example-model',
                     'base_url':'https://api.openai.com/v1', 'api_style':'responses'}

    def test_empty_settings_reveal_only_missing_configuration(self):
        settings = model_settings(self.environ)
        self.assertFalse(settings['configured'])
        self.assertFalse(settings['has_api_key'])
        self.assertEqual(settings['model'], '')
        self.assertEqual(settings['provider'], 'OpenAI')
        self.assertNotIn('api_key', settings)

    def test_saved_configuration_is_private_immediate_and_reloadable(self):
        result = save_model_settings(self.path, self.body, self.environ)
        self.assertTrue(result['configured'])
        self.assertNotIn(self.body['api_key'], json.dumps(result))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(self.environ['LLM_MODEL'], 'example-model')
        reloaded = {}
        load_local_config(self.path, reloaded)
        self.assertEqual(reloaded, self.environ)

    def test_existing_unrelated_settings_and_explicit_environment_are_preserved(self):
        self.path.write_text('# keep comment\nSHIP24_API_KEY=tracking-test-only\nOTHER_SETTING=keep-me\nLLM_MODEL=old-model\n')
        save_model_settings(self.path, self.body, self.environ)
        text = self.path.read_text()
        self.assertIn('SHIP24_API_KEY=tracking-test-only', text)
        self.assertIn('OTHER_SETTING=keep-me', text)
        self.assertEqual(text.count('LLM_MODEL='), 1)
        reloaded = {'LLM_MODEL':'explicit-process-model'}
        load_local_config(self.path, reloaded)
        self.assertEqual(reloaded['LLM_MODEL'], 'explicit-process-model')
        self.assertNotIn('OTHER_SETTING', reloaded)
        self.assertEqual(reloaded['LLM_API_STYLE'], 'responses')

    def test_first_configuration_requires_a_key(self):
        with self.assertRaisesRegex(ValueError, 'API Key'):
            save_model_settings(self.path, {**self.body,'api_key':''}, self.environ)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.environ, {})

    def test_blank_key_can_retain_same_provider_and_change_model(self):
        save_model_settings(self.path, self.body, self.environ)
        settings = save_model_settings(self.path, {**self.body, 'api_key':'', 'model':'new-model',
                                                  'base_url':'https://API.OPENAI.COM/v1/'}, self.environ)
        self.assertEqual(settings['model'], 'new-model')
        self.assertEqual(self.environ['LLM_API_KEY'], 'test-key-only')

    def test_changed_endpoint_never_reuses_existing_key(self):
        save_model_settings(self.path, self.body, self.environ)
        before = self.path.read_text()
        for base in ['https://different.example/v1','https://api.openai.com/different-path']:
            with self.subTest(base=base), self.assertRaisesRegex(ValueError, '更换接口'):
                save_model_settings(self.path, {**self.body, 'api_key':'', 'base_url':base}, self.environ)
        self.assertEqual(before, self.path.read_text())
        self.assertEqual(self.environ['LLM_BASE_URL'], self.body['base_url'])

    def test_new_key_allows_explicit_custom_provider_and_chat_format(self):
        settings = save_model_settings(self.path, {**self.body, 'api_key':'second-test-key',
                                                  'base_url':'https://custom.example/v1',
                                                  'api_style':'chat_completions'}, self.environ)
        self.assertEqual(settings['provider'], 'custom.example')
        self.assertEqual(settings['api_style'], 'chat_completions')
        self.assertNotIn('second-test-key', json.dumps(settings))

    def test_invalid_urls_are_rejected_before_any_write(self):
        for base in ['http://example.com/v1','https://user:password@example.com/v1',
                     'https://@example.com/v1','https://example.com/v1?token=x',
                     'https://example.com/v1?','https://example.com/v1#fragment',
                     'https://example.com:invalid/v1','https://example.com:0/v1',
                     'https://example.com/a b','https://example.com/"', '', '//example.com/v1']:
            if not base:
                continue  # Empty input deliberately selects the documented default.
            with self.subTest(base=base), self.assertRaises(ValueError):
                save_model_settings(self.path, {**self.body, 'base_url':base}, self.environ)
        self.assertFalse(self.path.exists())

    def test_invalid_payloads_and_environment_line_injection_are_rejected(self):
        bodies = [[], None, {'unexpected':'value'}, {**self.body,'model':{}},
                  {**self.body,'model':'bad model name'}, {**self.body,'model':'model\nSHIP24_API_KEY=bad'},
                  {**self.body,'api_key':'test\nLLM_MODEL=bad'}, {**self.body,'api_key':'test key'},
                  {**self.body,'api_key':'test"key'}, {**self.body,'api_style':'unknown'},
                  {**self.body,'base_url':['https://example.com']}]
        for body in bodies:
            with self.subTest(body=body), self.assertRaises(ValueError):
                save_model_settings(self.path, body, self.environ)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.environ, {})

    def test_write_failure_does_not_activate_unsaved_settings(self):
        with patch('parcel.config.os.replace', side_effect=OSError('test-only failure')):
            with self.assertRaises(OSError):
                save_model_settings(self.path, self.body, self.environ)
        self.assertEqual(self.environ, {})
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])


class ModelSettingsHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '.env.local'
        clean = {key:value for key,value in os.environ.items() if not key.startswith('LLM_')}
        self.env_patch = patch.dict(os.environ, clean, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.config_patch = patch.object(app, 'CONFIG_PATH', self.path)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    def request(self, body=None, headers=None, path='/api/model/settings'):
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type':'application/json', **(headers or {})})
        return urlopen(request, timeout=5)

    def test_configure_without_task_id_updates_health_and_hides_key(self):
        with self.request() as response:
            self.assertFalse(json.load(response)['configured'])
        with self.request({'api_key':'http-test-key-only','model':'example-model'}) as response:
            settings = json.load(response)
        self.assertTrue(settings['configured'])
        self.assertNotIn('http-test-key-only', json.dumps(settings))
        with self.request(path='/api/health') as response:
            health = json.load(response)
        self.assertEqual(health['mode'], 'model')
        self.assertEqual(health['model'], 'example-model')
        with self.request() as response:
            self.assertNotIn('http-test-key-only', response.read().decode())

    def test_missing_key_returns_actionable_error_without_configuration(self):
        with self.assertRaises(HTTPError) as error:
            self.request({'model':'example-model'})
        self.assertEqual(error.exception.code, 400)
        self.assertIn('API Key', json.load(error.exception)['error'])
        self.assertFalse(self.path.exists())

    def test_cross_origin_cannot_save_settings(self):
        with self.assertRaises(HTTPError) as error:
            self.request({'api_key':'http-test-only','model':'example-model'}, {'Origin':'https://unrelated.example'})
        self.assertEqual(error.exception.code, 403)
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
