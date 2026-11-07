# BENFRANK NBA mobile deployment

The mobile site and authenticated API ship together from
`benfrank-60-question-interrogation-20261106`. Do not merge main or enable
paid resources until the owner approves the concrete deployment.

## Prepared Render blueprint

`render.yaml` defines one Docker web service, a 5 GB disk mounted at
`/var/lib/benfrank`, and a generated 256-bit `BENFRANK_API_TOKEN` secret.
It explicitly selects the development branch and disables automatic deploys.
The Starter compute plan and disk are paid resources: get owner approval
before applying this blueprint. Published base pricing checked November 7,
2026: $7/month compute plus $1.25/month for the disk, before taxes, workspace
fees or usage beyond included allowances. Verify the account's actual quote.

After account access and cost approval:

1. Import the existing repository and branch as a Render Blueprint. Inspect
   existing services first to avoid creating a duplicate.
2. Apply the blueprint with the named service and disk, retaining any existing
   token value. `generateValue` generates a secret only when the variable is new.
3. Deploy the tested branch commit. Verify build logs, `/health`, the mounted
   disk and generated HTTPS URL. Keep the service to one ASGI worker.
4. Obtain the generated access token from Render's environment settings through
   a secure account session. Never commit or paste it into a report or URL.
5. Open the service root on iPhone/iPad, enter the token, full player name,
   market, exact line, and a future completion deadline before tipoff.
6. Submit one job, poll its status, download its receipt and evidence ZIP,
   restart the service, and verify the same terminal job and files remain.
7. Run a fresh future prop on the deployed service and reverify the stored
   source hashes, simulations, blind process, deadline, and ledger insertion.

## Request and authentication contract

- `GET /` serves the responsive mobile interface. `/mobile.js`, `/mobile.css`
  and `/health` are public; API routes and the OpenAPI schema require bearer auth.
- `POST /api/run-framework` accepts multipart `player`, `market`, `line`, and
  timezone-aware `pregame_cutoff`. It returns HTTP 202 and a saved job ID.
- The cutoff's Eastern date selects the NBA slate, including games crossing
  midnight UTC. The exact player, market and line are selected from the live
  native board **before** the usual batch sampling limit is applied.
- Acquisition and actual prediction issuance must precede the requested
  deadline and tipoff. A queued job is never a verified prediction.
- `GET /api/jobs/{id}` returns status, exact blockers and, after verification,
  a concise prediction summary and historical windows.
- `GET /api/jobs/{id}/receipt` downloads the execution receipt with authentication.
  `GET /api/jobs/{id}/artifacts` downloads that job's immutable requests, events,
  prediction receipts and trial traces. Raw provider bytes are held in the
  disk's shared `jobs/state/raw` directory and referenced by the source manifest;
  the per-job ZIP does not duplicate all shared source bytes.
- Tokens must contain at least 32 ASCII characters. The page uses only its own
  origin and does not put tokens in local/session storage or query strings.
- Missing authentication returns 401; missing/short server secrets or unavailable
  required storage return 503; invalid inputs return 422; a busy runner returns
  429. Oversized requests return 413 before multipart parsing.

## Storage and restart behavior

All new requests, source captures, acquisition state, predictions, trial traces,
job events and forward ledger entries live beneath the mounted directory.
Legacy warehouse files and governing rules remain in the repository and are
not opened for writes by this adapter. Job event files and requests are
append-only. `job.json` is a replaceable status index.

Completed jobs and receipts survive process restarts when the disk is attached.
An active job interrupted by a restart is explicitly marked `interrupted` on
startup. It is not silently resumed or called complete. Submit a new job with
new source clocks and a fresh deadline if it still qualifies as pregame.

One job runs at a time in the single service process to avoid concurrent writes
to the shared acquisition/forward ledger. Jobs run in a background thread;
there is no separate durable execution queue in this deployment.

## Verification

Install production requirements and `mobile/requirements-test.txt`, then run:

```sh
python -m compileall -q mobile
python -m unittest discover -s tests -v
python -m playwright install --with-deps webkit
python scripts/test_mobile_browser.py --output mobile-browser-results
```

The GitHub mobile workflow also builds the Docker image, mounts a test disk,
checks container readiness and verifies authenticated routes. Browser tests
use WebKit with iPhone/iPad emulation, not physical Apple hardware. Their model
run is an explicitly blocked software fixture. The optional `--actual-job`
flag displays an existing genuine verified job without generating a forecast.

A live local API run on November 7 completed 25,000 main plus two 2,000-trial
stress runs for Aaron Gordon points 13.5, using then-current source captures.
Its traces and pregame receipt were independently reread and sampled games
reexecuted. This is evidence of that run, not evidence of a Render deployment.
See `diagnostics/mobile-validation-20261107.json` for current execution details.

## Remaining analytical limits

Raw simulation side shares are uncalibrated. The isolated Blind model's process
separation is tested, but its predictive accuracy is not independently certified.
Defender tracking, some DNA questions, full career history and other unobserved
inputs remain unavailable where explicitly recorded. Stress assumptions are
proxies, not observed tracking opportunity/conversion data. Native board feeds,
injury/depth sources and historical feeds can block any subsequent request;
the API retains the exact source or stage failure. Screenshot extraction is not
implemented, so the mobile form uses manually confirmed player/market/line fields.
