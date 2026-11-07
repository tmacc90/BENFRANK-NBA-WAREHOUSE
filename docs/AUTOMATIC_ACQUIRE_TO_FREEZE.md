# Automatic NBA acquisition → prediction → freeze

This adds an automatic execution mode to `run_framework.py`. All existing input,
config, OMNI, governing, historical-data and receipt interfaces are preserved.
The new state database is append-only; derived `games` databases are created only
at new run paths. No original warehouse migration is performed.

```bash
python run_framework.py --auto configs/auto_future_20261107.json \
  --state-dir auto_state --output auto_runs/NEW_UNIQUE_RUN
```

The configuration supplies the NBA game date, a maximum number of props/games,
and up to three ESPN end-year seasons. Discovery reads actual standard public
PrizePicks projections, excludes live/promo/one-sided offerings, matches teams
and tipoff to ESPN, and selects at most two distinct players per game. The
sampling order is declared before model execution. Fewer lines can be available
than the configured maximum; the discovery receipt shows the exact board.

## Executed stages and evidence

1. Raw source bodies are content-addressed and retain their actual retrieval
   clocks, provider families, URL and SHA256. Network failures remain evidence.
2. ESPN player IDs come from exact normalized source-team depth identities.
   Per-player season logs use ESPN's **season end year**, reject preseason,
   all-star and malformed rows, and validate shot scoring and count statistics.
3. Hash-pinned NBA Stats mirror boxes/schedule supply a fallback independently
   upstream from ESPN. They are labeled archived mirror data, never direct NBA
   responses. ESPN aliases such as NO/NOP, GS/GSW and NY/NYK are canonicalized.
4. Date plus unordered team pair identifies a candidate game; conflicting home
   designations, IDs, counts or materially different timestamps quarantine all
   variants. This handles neutral-site differences without duplicate games.
   Missing fields are merged only after all observed values agree. ESPN rounded
   minutes tolerate a maximum 1.01-minute difference from second-precision boxes.
5. Target/future games are filtered before conflict resolution. Recent ESPN log
   appearances need a completed summary; otherwise an eight-hour conservative
   buffer applies. Historical correction vintage remains explicitly unverified.
6. L5/L10/L15/L20/L25/L32/L52, current/previous season and available archive windows
   retain exact game IDs and OVER/UNDER/PUSH counts. A target needs 52 genuine
   eligible games to enter this automatic physical execution mode. Fewer genuine
   appearances produce a coverage blocker, never invented games.
7. Existing `History.profile` mathematics is fed reconciled player shooting and
   box counts. Five complete prior team boxes supply matchup and pace estimates.
   Depth projections, injury uncertainty and required replacement starters feed
   existing v5.2 rotation scenarios; final starters are not required.
8. The existing v5.2 complete-game possession simulator runs **25,000 actual
   sequential main games per prop** plus 2,000 downside and 2,000 upside games.
   Every main/stress trial has a compressed JSONL trace, deterministic seed,
   complete final score and target outcome. A separate reader reproduces trace
   counts and hashes. A bootstrap is never substituted for complete-game trials.
9. The existing independent numerical ridge worker receives only numerical
   training rows, a candidate feature vector and regularization. Its returned
   input hash must match the actual sanitized payload. This proves process and
   feature separation; it does **not** establish independent predictive accuracy.
10. Both opposing-case stresses and the blind disagreement remain in the receipt.
    The exact-line ladder, +0.5, +1.0 and flip point rethreshold genuine main draws;
    no extra simulation counts are claimed for those calculations.
11. Existing 100-test Player DNA and all 60 interrogation questions are emitted.
    Unobserved tracking/causal/validation/calibration questions stay unavailable.
12. Only a fully completed forecast actually inserted **before tipoff** enters
    the immutable existing v5.2 forward ledger. All revisions survive; the original
    first forecast remains the scorecard observation.

## Historical screenshots

```bash
python run_framework.py --auto configs/auto_screenshots_20261106.json \
  --state-dir auto_state --output auto_runs/NEW_HISTORICAL_AUDIT
```

The six original exact lines remain those in `benfrank_six_prop_batch.py`. The
original pregame cutoff and archived pregame role/injury snapshots were not
provided. Acquisition and historical windows can execute, but the current
historical replay is deliberately gated until a separately implemented archive
input path can substantiate those clocks and observations. Current depth/injury
captures are acquisition identity aids only; they cannot stand in for original
pregame snapshots. No historical screenshot is entered into a forward cohort.

## Verification and grading

```bash
python -m unittest discover -s tests -v
python scripts/verify_auto_run.py --run auto_runs/COMPLETED_RUN --state auto_state
python scripts/grade_auto_predictions.py --state auto_state --output grading/NEW_RUN
```

Verification re-reads raw source bytes, prediction hashes, immutable ledger clocks,
and all main/stress trace bytes. Grading retains completed ESPN summaries and
appends settlements. Unplayed games, DNP and platform void ambiguity remain
pending/unresolved; neither the frozen decision nor its timestamp is rewritten.

GitHub Actions runs the full test suite and a real forward workflow on relevant
pushes to the requested branch. All raw, reconciliation, trace and ledger evidence
is uploaded even on failure. `benfrank-auto-grade.yml` can restore that exact
artifact for postgame grading. Neither workflow pretends a branch-only cron is
active on the default branch; a separately scheduled task can run the grading.

## Remaining accuracy boundaries

This is an unvalidated research challenger. It does not certify a betting edge,
independently validated Blind AI accuracy, calibrated probabilities, genuine full
career coverage, complete shot/defender tracking or platform-native settlement.
NBA CDN access failures, partial provider coverage and unresolved disagreements
are reported with actual source evidence. An expired forward configuration must
be advanced to a new real future slate, never backdated.

## Supplied captured-board execution in CI

The initial published Actions run retrieved ESPN's schedule but received HTTP
403 from the native PrizePicks endpoint. The captured-board input route accepts
the already lawfully acquired public response in `data/board_captures/`, verifies
the original bytes and receipt hashes, and retains the original retrieval clock.
The current ESPN schedule, depth, injury and player-history inputs are still
acquired normally. An actual current import clock and a new revision ID are
recorded; neither a line capture nor a prediction is backdated. Captures older
than 24 hours and games already at tipoff are rejected.

`scripts/run_auto_ci.py` attempts live discovery first. It uses the supplied
capture only for the specifically documented native-provider HTTP 403. Other
acquisition or model failures remain failures. The CI route receipt explicitly
retains `BLOCKED_NATIVE_PROVIDER_HTTP_403` and
`current_native_line_recheck: false`, even if the full captured-board model run
succeeds. A green captured-board job is not proof of working live discovery.

```bash
python run_framework.py --auto configs/auto_captured_forward_20261107.json \
  --state-dir auto_state --output auto_runs/NEW_CAPTURED_BOARD_RUN
```
