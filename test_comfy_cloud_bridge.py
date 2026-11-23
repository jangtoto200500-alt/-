import json
import os
import unittest
from unittest.mock import patch

import comfy_cloud_bridge as bridge


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, n):
        return self.payload[:n]


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {"3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}}
        self.request_id = "00000000-0000-4000-8000-000000000001"

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key(self):
        self.assertFalse(bridge.status()["configured"])

    @patch.dict(os.environ, {"COMFY_CLOUD_API_KEY": "dummy"}, clear=True)
    def test_readiness_not_same_as_connection(self):
        self.assertFalse(bridge.status()["connected"])

    @patch.dict(os.environ, {"COMFY_CLOUD_API_KEY": "dummy"}, clear=True)
    def test_non_billable_probe(self):
        with patch.object(bridge, "urlopen", return_value=FakeResponse({"id": "me"})) as mocked:
            self.assertTrue(bridge.status(check_connection=True)["connected"])
            self.assertEqual(mocked.call_args.args[0].get_header("X-api-key"), "dummy")

    @patch.dict(os.environ, {"COMFY_CLOUD_API_KEY": "dummy"}, clear=True)
    def test_default_blocks_billing(self):
        with patch.object(bridge, "urlopen") as mocked:
            with self.assertRaises(bridge.ComfyCloudError):
                bridge.submit(self.workflow, request_id=self.request_id, confirmed=True)
            mocked.assert_not_called()

    @patch.dict(os.environ, {"COMFY_CLOUD_API_KEY": "dummy", "COMFY_CLOUD_GENERATION_ENABLED": "true"}, clear=True)
    def test_generation_requires_confirmation(self):
        with patch.object(bridge, "urlopen") as mocked:
            with self.assertRaises(bridge.ComfyCloudError):
                bridge.submit(self.workflow, request_id=self.request_id, confirmed=False)
            mocked.assert_not_called()

    def test_ui_workflow_is_rejected(self):
        with self.assertRaises(bridge.ComfyCloudError):
            bridge.validate_workflow({"nodes": [{"id": 1}]})

    @patch.dict(os.environ, {"COMFY_CLOUD_API_KEY": "dummy", "COMFY_CLOUD_GENERATION_ENABLED": "true"}, clear=True)
    def test_v2_submission(self):
        with patch.object(bridge, "urlopen", return_value=FakeResponse({"id": "job-123", "status": "queued"})) as mocked:
            response = bridge.submit(self.workflow, request_id=self.request_id, confirmed=True)
            self.assertEqual(response["status"], "queued")
            request = mocked.call_args.args[0]
            self.assertEqual(request.full_url, "https://cloud.comfy.org/api/v2/jobs")
            self.assertEqual(request.get_header("Authorization"), "Bearer dummy")
            self.assertEqual(json.loads(request.data)["workflow"], self.workflow)


if __name__ == "__main__":
    unittest.main()
