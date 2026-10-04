import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).parents[1] / 'controller'))
import pi_inference as bridge


class SubscriptionBridge(unittest.TestCase):
    def test_auth_tool_boundary_stream_and_provider_failure(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.handler('x' * 32, Path('/existing/auth'), 'test-image'))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{server.server_port}/v1/chat/completions'
        def request(payload, authorized=True):
            return urlopen(Request(url, data=json.dumps(payload).encode(), headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + ('x' * 32 if authorized else 'wrong')}), timeout=2)
        body = {'model': bridge.MODEL, 'messages': [{'role': 'user', 'content': 'Return OK'}], 'stream': True}
        try:
            with patch.object(bridge, 'infer', return_value=('OK', {'total_tokens': 2})) as infer:
                for payload, authorized, code in [(body, False, 401), (dict(body, tools=[{}]), True, 400), (dict(body, model='other'), True, 400)]:
                    with self.assertRaises(HTTPError) as error:
                        request(payload, authorized)
                    self.assertEqual(error.exception.code, code)
                infer.assert_not_called()
                with request(body) as response:
                    content = response.read().decode()
                self.assertIn('"content": "OK"', content); self.assertIn('data: [DONE]', content)
                with request(dict(body, tools=[{'type': 'function', 'function': {'name': 'tool_call'}}])) as response:
                    self.assertIn('data: [DONE]', response.read().decode())
                self.assertEqual(infer.call_args.args[0], body['messages'])
                infer.side_effect = RuntimeError('upstream')
                with self.assertRaises(HTTPError) as error:
                    request(body)
                self.assertEqual(error.exception.code, 502)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_completed_pi_response_required(self):
        event = {'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'stop',
                 'content': [{'type': 'text', 'text': 'OK'}], 'usage': {'input': 3, 'cacheRead': 2, 'output': 1, 'totalTokens': 6}}}
        self.assertEqual(bridge.completion(json.dumps(event)), ('OK', {'prompt_tokens': 5, 'completion_tokens': 1, 'total_tokens': 6}))
        event['message']['stopReason'] = 'error'
        with self.assertRaises(ValueError): bridge.completion(json.dumps(event))


if __name__ == '__main__': unittest.main()
