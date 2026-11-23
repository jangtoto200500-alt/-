"""Comfy Cloud v2 adapter for the 원리한입 Render service.

The adapter never schedules work or publishes to YouTube. Billable generations
require an enabled server flag and explicit per-request confirmation.
"""
from __future__ import annotations

import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://cloud.comfy.org"
MAX_RESPONSE_BYTES = 2_000_000
MAX_NODES = 250


class ComfyCloudError(RuntimeError):
    pass


def configured() -> bool:
    return bool(os.environ.get("COMFY_CLOUD_API_KEY", "").strip())


def generation_enabled() -> bool:
    return os.environ.get("COMFY_CLOUD_GENERATION_ENABLED", "").strip().lower() == "true"


def _api(path: str, *, method: str = "GET", payload: dict | None = None, v1: bool = False,
         idempotency_key: str | None = None) -> dict:
    key = os.environ.get("COMFY_CLOUD_API_KEY", "").strip()
    if not key:
        raise ComfyCloudError("missing_api_key")
    if not path.startswith("/api/") or "?" in path or "#" in path or ".." in path:
        raise ComfyCloudError("invalid_api_path")
    headers = {"Accept": "application/json"}
    if v1:
        headers["X-API-Key"] = key
    else:
        headers["Authorization"] = "Bearer " + key
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = str(uuid.UUID(idempotency_key))
    request = Request(BASE_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() if hasattr(response, "headers") else ""
        if mime and mime not in ("application/json", "application/problem+json") and not mime.endswith("+json"):
            # Do not include provider response bodies; they could hold private content.
            reason = "html" if mime == "text/html" else "text" if mime == "text/plain" else "other"
            raise ComfyCloudError("provider_non_json_" + reason)
        if not raw.strip():
            raise ComfyCloudError("provider_empty_response")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ComfyCloudError("response_too_large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ComfyCloudError("unexpected_api_response")
        return result
    except HTTPError as error:
        raise ComfyCloudError("provider_http_" + str(error.code)) from None
    except (URLError, TimeoutError):
        raise ComfyCloudError("provider_unreachable") from None
    except (ValueError, UnicodeError):
        raise ComfyCloudError("provider_invalid_json") from None


def status(*, check_connection: bool = False) -> dict:
    result = {"configured": configured(), "generation_enabled": generation_enabled(),
              "api_version": "v2", "base_url": BASE_URL, "connected": False}
    if not check_connection or not result["configured"]:
        return result
    try:
        _api("/api/user", v1=True)
        result["connected"] = True
    except ComfyCloudError as error:
        result["diagnostic"] = str(error)
    return result


def validate_workflow(workflow: dict) -> dict:
    if not isinstance(workflow, dict) or not 1 <= len(workflow) <= MAX_NODES:
        raise ComfyCloudError("invalid_workflow_size")
    if "nodes" in workflow or "links" in workflow:
        raise ComfyCloudError("export_api_format_required")
    for node_id, node in workflow.items():
        if not str(node_id).isdigit() or not isinstance(node, dict):
            raise ComfyCloudError("invalid_node")
        if not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ComfyCloudError("invalid_node_schema")
    if len(json.dumps(workflow, ensure_ascii=False).encode("utf-8")) > 230_000:
        raise ComfyCloudError("workflow_too_large")
    return workflow


def submit(workflow: dict, *, request_id: str, confirmed: bool,
           partner_nodes: bool = False) -> dict:
    if not confirmed or not generation_enabled():
        raise ComfyCloudError("generation_not_enabled_or_unconfirmed")
    validate_workflow(workflow)
    request_id = str(uuid.UUID(request_id))
    payload = {"workflow": workflow}
    if partner_nodes:
        payload["extra_data"] = {"api_key_comfy_org": os.environ["COMFY_CLOUD_API_KEY"].strip()}
    response = _api("/api/v2/jobs", method="POST", payload=payload, idempotency_key=request_id)
    if not response.get("id"):
        raise ComfyCloudError("job_id_missing")
    return {"id": response["id"], "status": response.get("status", "submitted")}


def job(job_id: str) -> dict:
    job_id = str(uuid.UUID(job_id))
    response = _api("/api/v2/jobs/" + job_id)
    return {"id": response.get("id", job_id), "status": response.get("status", "unknown"),
            "outputs": response.get("outputs", []), "progress": response.get("progress")}


def asset(asset_id: str) -> dict:
    asset_id = str(uuid.UUID(asset_id))
    response = _api("/api/v2/assets/" + asset_id)
    return {"id": response.get("id", asset_id), "url": response.get("url"),
            "url_expires_at": response.get("url_expires_at"),
            "mime_type": response.get("mime_type")}
