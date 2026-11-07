# BENFRANK Mobile API Deployment

Research-only deployment blueprint. No hosted app, successful job, or model certification is implied by a committed file.

## Render

1. In Render, create a Blueprint from this repository and select the development branch.
2. Review the paid Starter web service and persistent disk charges before deploying; this blueprint requires persistent disk storage.
3. Set a long random BENFRANK_API_TOKEN as a server secret in the Render environment settings. Never commit it.
4. Deploy; Render provides an HTTPS URL. Use that URL at the mobile app page root. The app and API are on the same origin.
5. Enter your bearer token in the mobile page, player, market, line, timezone-aware future cutoff, then run.
6. Inspect /api/jobs/<job_id> with bearer token, and the on-disk execution/execution_receipt.json. Do not claim a verified forecast merely because a job was queued.

## Limitations

- Exact manual player + line is currently used to check native-board-discovered props, NOT to inject a guaranteed exact line. If it is not in the public board, the job returns incomplete.
- Screenshot bytes are explicitly rejected until a trustworthy extraction and confirmation endpoint exists.
- Backend thread jobs do not survive restart. Persisted status reports interrupted; true durable queue workers are a separate dependency.
- Never expose this API without TLS, token authentication, network protections and abuse controls. The /health endpoint and landing page are public. Token is entered per browser session; not saved.
- A service running the framework can generate considerable data traffic, storage and compute cost.
- Simulations and pregame receipts are unverified until a live end-to-end run demonstrates their stage provenance. Discovery, actual data feeds, independent blind model and calibration can still block.
- Before use with real stakes, review local betting restrictions and data source terms.

## Smoke test

Run `python -m compileall -q mobile`, then `python -m unittest discover -s tests -v`. For API import check install both requirement files and run `python -c "from mobile.api import app; print(app.title)"`.

The repository's preserved v5.2/v6 runner is invoked as-is. No previous prediction receipts, training data, or governing code are deleted.
