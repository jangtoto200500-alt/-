# 원리한입 — Comfy Cloud → Render 연결

2026-11-23. This integration is **prepared, not authenticated or active**. Do not interpret a merged PR or a passing unit test as evidence of video generation or YouTube publication.

## Architecture / boundaries

1. Existing daily editorial automation proposes one original Short, first checking Notion and the actual YouTube channel to avoid duplicates.
2. Export a **ComfyUI API-format** image-to-video or text-to-video workflow from Comfy Cloud (File → Export (API)); verify models and assets exist in the Cloud workspace.
3. An authenticated Render operator submits the workflow to Comfy API v2, and polls the returned job UUID. Comfy GPU time consumes credits.
4. Inspect the actual outputs, download the source video clips, assemble Korean speech/music/SRT and render an H.264/AAC 1080×1920 MP4. **That renderer is not yet implemented in this repository.**
5. Pass media-rights, playback, audio, subtitle, originality and channel duplicate QA before invoking the existing YouTube uploader. **Automatic publish from Comfy outputs is not implemented.** No output is public by default.

## One-time owner setup (never paste secrets into GitHub/Notion/chat)

1. Log in yourself at https://cloud.comfy.org/ and check the subscription/credits. Cloud API requires a paid active subscription: https://comfy.org/pricing .
2. Create the API key at https://platform.comfy.org/profile/api-keys .
3. In https://dashboard.render.com/web/srv-dbksbe3ncjis73f7b3a0 > Environment, add `COMFY_CLOUD_API_KEY` as a **secret** value. Keep `COMFY_CLOUD_GENERATION_ENABLED=false` until a billable test is authorized. Do not add the key to a committed file or document.
4. Deploy after review and authenticate to the existing password-protected Render dashboard. `GET /api/comfy/status` validates the account connection via the non-billable v1 `GET /api/user` endpoint (keys are never returned). Any `401` or inactive-plan response requires owner action.

## Protected Render API endpoints

The new routes use the existing HTTP Basic administrator authentication.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/comfy/status` | Non-billable connection check and enabled flag |
| GET | `/api/comfy/jobs/{uuid}` | Read Comfy API v2 job status and outputs |
| GET | `/api/comfy/assets/{uuid}` | Read output asset metadata and short-lived signed download URL |
| POST | `/api/comfy/submit` | Submit an API-format workflow to Comfy v2; billable and gated |

`POST /api/comfy/submit` only works when **all** of the following are true: valid administrator authentication, API key present, `COMFY_CLOUD_GENERATION_ENABLED=true`, header `X-Comfy-Billable-Confirm: generate`, and a JSON body with `workflow` (API-format object), `request_id` (new UUID per attempt), and optional Boolean `partner_nodes`. The idempotency UUID prevents accidental duplicate submits. **An ambiguous network timeout must not be retried with a new UUID without first confirming job status.**

Example request body (replace the placeholder with a real exported workflow; it is NOT a working video template):

```json
{
  "workflow": {"3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}}},
  "request_id": "00000000-0000-4000-8000-000000000001",
  "partner_nodes": false
}
```

The example is schematic and deliberately not runnable as-is. Video model, duration, prompt, character references and node IDs must come from the actual exported workflow.

**Not yet enabled:** scheduled Comfy generations, video editing and sound mixing, QA media validation, durable job records across Render restarts, and autonomous YouTube upload. These steps require a user-connected Comfy account and tested video workflow before activation. The existing `/upload` endpoint remains unchanged and defaults to a private YouTube upload.

## Security / operations

- HTTPS host fixed to `cloud.comfy.org`; credentials are environment-only. Provider response bodies and API keys are never logged.
- Keys are not sent to client responses; output URLs are short-lived and only returned after administrator authentication.
- No new webhook, unauthenticated generator, cron job, or public uploader is introduced. No credits are consumed by deployment or connection probes.
- Do not enable billable generations or public uploads merely because a daily ChatGPT automation is scheduled.
- Run `python -m unittest -v test_comfy_cloud_bridge` before deployment.

References:
- https://docs.comfy.org/api-reference/v2/overview
- https://docs.comfy.org/development/cloud/overview
- https://docs.comfy.org/development/cloud/api-reference (deprecated v1, used only for account probe)
