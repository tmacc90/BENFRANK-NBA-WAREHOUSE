# 🏀 BENFRANK — FREE iPhone/iPad Run Framework

**No Render, paid API, paid database or recurring hosting subscription is required.**
The existing Python engine runs inside a standard GitHub-hosted `ubuntu-latest` worker on a **public** repository. GitHub currently offers standard-hosted runner time free in public repos, subject to GitHub's usage policies and storage limits. Do not buy larger runners, storage extensions or paid hosting.

## How to launch from an iPhone

1. Sign into GitHub.com in **Safari** (use **Request Desktop Website** if the Actions controls are hidden).
2. Open https://github.com/tmacc90/BENFRANK-NBA-WAREHOUSE/actions/workflows/benfrank-free-launcher.yml
3. Choose **Run workflow**. The launcher runs the preserved BENFRANK prediction engine from branch `benfrank-60-question-interrogation-20261106`, **without merging** that branch into `main`.
4. Leave **NBA slate date = today** for the current Eastern-time slate, or enter YYYY-MM-DD for a later slate.
5. Required: Enter **Player**, **Market**, and **Exact line** together. Example: `Example Player`, `points`, `22.5`. Omit all three to use native-board discovery with the max props/game options.
6. Tap **Run workflow**.
7. Open the run to read executed steps. A blocked source or missing model receipt is a *failed/incomplete* execution, not a successful prediction.
8. Under **Artifacts**, download `benfrank-free-run-...`. Open `free-run-output/mobile_report.html` on your iPhone, and keep `execution_receipt.json` for an auditable outcome.

The report is rendered strictly from real engine execution receipts. It never manufactures trial counts, OVER/UNDER results, or certificates.

## What the workflow does

- Uses the **existing** `run_framework.py --auto` engine in `manual_forward_prop` mode, not a replacement mock predictor.
- Selects a future NBA slate and resolves your manually entered player against ESPN scheduled games and published depth charts. It then requests free ESPN / independent historical data through the existing source pipeline.
- The PrizePicks public API returned HTTP 403 in a verified GitHub Actions run on November 7, 2026. The manual path **does not call that endpoint**. The submitted line is user-entered, **not independently verified as an available PrizePicks line**. Team, player and future matchup must resolve from ESPN or the run fails without guessing.
- Attempts the existing L5/L10/L15/L20/L25/L32/L52 histories, player identity reconciliation, matchup/role evidence, **25,000 main trials per prop**, separate stress runs, Blind model, 60-question check, and pregame freeze.
- Writes an execution receipt with specific blockers and stage evidence, plus an offline phone-readable HTML report.
- Uses `workflow_dispatch` only. It does **not** auto-run every day or incur scheduled resource consumption.

## Screenshots on iPhone

There is no dependable free screenshot-to-GitHub dispatch integration in this no-server route. Use iPhone Live Text to copy the player and prop line from the screenshot, then paste them into the Run workflow inputs. OCR or uploaded screenshot extraction is **not** claimed as implemented.

## Storage and costs

- The workflow uses standard runners and does not set up a paid service.
- To limit artifact storage, reports and selected JSON receipts expire automatically after **3 days**. Save the artifact ZIP to Files if you want a longer-term ledger; GitHub Actions artifacts are not permanent storage.
- The run workspace is temporary. Each workflow starts fresh; historical data and state cannot magically persist between jobs without separate artifact restore or a repository-managed storage process.
- The public repository and its workflow data may be visible to others. Do not put personal secrets in workflow input fields or artifacts.
- Free external sports endpoints can be blocked, rate-limited, incomplete, or legally restricted. The framework must surface the exact failure. No odds, accuracy, calibration or betting profit guarantee is offered.

## Verification and boundaries

Code committed ≠ successful live run. The first test is to manually run the launcher for a **future** NBA slate, retrieve the receipt and verify simulation provenance and source timestamps. Do not label an incomplete run FULL. Keep the existing warehouse and prediction receipts untouched.

The earlier Render API, Docker and mobile PWA are **optional legacy alternatives**, not required to use this free route. Do not activate a paid Render blueprint.
