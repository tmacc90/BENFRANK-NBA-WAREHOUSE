# BENFRANK OMNI-GOD v1.0 — implemented execution runtime

The master design now has executable source adapters, per-sport statistical
simulations, a separate-process line-blind model, immutable reports, grading,
chronological calibration, CI, and isolated repository deployment packages.
Implementation and software validation do not establish betting accuracy.

## Run Framework

```bash
python run_framework.py --omni uploaded_props.json --output omni_runs/my_run --state-dir omni_state
```

This collects all sources first, freezes a cutoff, runs every supplied prop,
creates OVER/UNDER forecasts when sufficient comparable evidence exists, and
independently verifies all saved simulation draws. It does not require a second
command to finish modeling. One failed prop does not suppress other results.
Exit 2 means at least one prop was blocked; the report gives its exact reason.
The existing `--input` NBA historical-research and `--config` physical v6 modes
retain their original behavior.

Screenshots are transcribed into the exact manifest below. The runtime does not
claim that OCR, native PrizePicks discovery, or bookmaker authentication is
implemented. A connected public board can instead provide the same props
contract through `board_source: {"url": "https://..."}`. Source bytes are saved.

```json
{
  "mode": "PREGAME",
  "props": [{
    "sport": "NBA",
    "player": "FULL NAME FROM UPLOADED PROP",
    "player_id": "ESPN_NUMERIC_ID",
    "team_id": "ESPN_TEAM_ID",
    "market": "points",
    "line": 22.5,
    "opponent": "ESPN_OPPONENT_TEAM_ID",
    "event_id": "ESPN_EVENT_ID",
    "event_start_utc": "ACTUAL_START_WITH_TIMEZONE",
    "captured_at_utc": "ACTUAL_LINE_CAPTURE_WITH_TIMEZONE",
    "line_source": "USER_SCREENSHOT_OR_PUBLIC_BOARD_SOURCE",
    "platform": "PrizePicks",
    "scope": "FULL_GAME",
    "rules": {"push": "PUSH", "void": "PLATFORM_DNP_RULE"},
    "history_sources": [{"provider": "espn"}]
  }]
}
```

The placeholders are intentionally invalid until replaced by the uploaded
prop's actual identifiers and times. For a live run omit `cutoff_utc`; collection
finishes before the automatic freeze. An explicit cutoff rejects sources first
captured after it. `RESEARCH_REPLAY` permits retrospective collection but is
labelled as research and is excluded from forward calibration. Never relabel
one as a pregame receipt.

Automatic ESPN season selection reads the athlete profile's current season
year, including the next-calendar-year convention for NBA/NHL, rather than
assuming calendar year. Supply `seasons:[...]` for explicit historical periods.
Replayed opponent-team schedules also require an explicit `opponent_season`.

## Sport/source coverage

| Sports | Implemented source path | Verification scope |
|---|---|---|
| NBA, WNBA, NCAAB, NFL, CFB, NHL, MLB | ESPN athlete profile + named game-log columns; event, roster/depth, opponent game-box captures | Secondary, source-attributed statistics; not independent official-source certification |
| Soccer | ESPN competition-specific logs + explicit league and extra-time rules | Rejects other competitions even when the endpoint returns them |
| F1 | Jolpi/Ergast driver results and qualifying | Explicit session; positions keep their own numeric meaning |
| Tennis | Configured Sackmann-format CSV or normalized JSON | Surface/best-of filters; unknown match dates get a conservative 21-day tournament availability boundary |
| COD, CS2, MMA, Boxing, Golf, Dota 2, LoL, Valorant, Table Tennis | Configured normalized JSON HTTPS provider or hashed data export | Implemented input/collection route; an accessible real source must be configured and verified separately |

No specialist API URL or credentials are invented. A blocked/empty source is
recorded, the next configured provider is tried, and a missing source gives an
explicit blocker. The same applies to markets missing from a provider: missing
statistics and DNPs never become zero. Provider support is market-dependent.
Soccer passes, tennis breaks and other fields absent from a public feed need a
normalized provider containing the actual observed statistic.

NHL official API and specialist feeds returning access errors are not marked
verified merely because an ESPN or user-export fallback exists. No anti-bot
challenge bypass is included.

## Normalized specialist contract

```json
{
  "sport": "CS2",
  "captured_at_utc": "ACTUAL_CAPTURE_TIME",
  "games": [{
    "sport": "CS2", "player": "FULL NAME", "player_id": "SOURCE_ID",
    "game_id": "SERIES_ID:MAP_NUMBER", "start_utc": "ACTUAL_START_TIME",
    "completed_utc": "ACTUAL_END_TIME", "completed": true,
    "season": "2026", "scope": "MAP_1", "opponent": "OPPONENT_SOURCE_ID",
    "stats": {"kills": 21, "headshots": 9}, "workload": 24, "workload_unit": "ROUNDS",
    "context": {"title": "CS2", "patch": "ACTUAL_PATCH", "series_format": "BO3"}
  }]
}
```

Configure `{"provider":"normalized_json","url":"https://provider/..."}` or
`{"provider":"normalized_json","file":"export.json","sha256":"EXACT_FILE_HASH"}`.
The collector assigns the raw response hash, URL and retrieval timestamp; row
metadata cannot override it. Uploaded data is labelled as uploaded, not
independently verified. Providers may be listed in fallback order.

For specialist live forecasts, also supply `event_source` with the same URL or
hashed-file configuration. Its JSON `event` object must contain `sport`,
`player`, `player_id`, `event_id`, `opponent`, `start_utc`, `scope`,
`status:"SCHEDULED"`, and the applicable sport `rules`. It is checked against
the request; it is not promoted into independent official verification.

Sport rules are mandatory for surface/format, patch/title/series, competition,
extra time, combat scheduled rounds, course/round and F1 session where relevant.
Scopes are exact: a series total cannot silently become a single-map prediction.
Fantasy scores require the platform's explicit `scoring_weights`; no shared
cross-sport fantasy formula is assumed. All numeric comparison decisions use
OVER/UNDER even when a lower finishing position is a better real-world finish.

## What actually executes

1. Exact prop/line/source/rules freeze; raw inputs preserved.
2. Player ID/name/sport checks; no cross-sport fallback.
3. Completed histories before cutoff; conflicting duplicates fail.
4. L5/L10/L15/L20/L25/L32/L52, explicit current/previous season or clearly
   labelled latest-fetched seasons, and all-fetched coverage. Partial windows
   keep their true denominator; all-fetched is not called complete career.
5. Exact-line streaks, OVER/UNDER examples and observed workload associations.
6. Same-opponent evidence and available recent opponent-box totals. Missing
   positional defense, schemes, tracking and league ranks remain explicit gaps.
7. Recent observed workload median or a sourced supplied workload projection.
   Final starters are not a requirement. Availability remains an explicit risk.
8. **25,000 baseline empirical statistic draws per prop, plus 25,000 in each
   of two stress scenarios**. Every trial is persisted with source game ID.
9. Separate-process chronological ridge, numerically sanitized and line-blind.
   It uses the same observed history with a different algorithm; this is
   process separation, not independent data or validated AI superiority.
10. Opposite-side stress, disagreements, scenario reversals, and hypothetical
    -2/-1/-0.5/exact/+0.5/+1/+2 sensitivity using the same baseline draws.
11. Eligible calibration applied, otherwise raw probabilities labelled
    uncalibrated. Monte Carlo precision is not predictive confidence.
12. OVER/UNDER, evidence gaps, report/chart, append-only forecast ledger and an
    independent replay of saved draws to verify counts and probabilities.

The engine is an empirical workload/bootstrap model, **not a full physical
possession-, play-, round- or point-by-point simulator**. Historical associations
are not invented causal explanations. Streaks do not automatically reverse or
continue. A blocked forecast cannot be forced into a fabricated side.

## Grade and calibrate

```bash
python -m benfrank_omni settle --sport NBA --input completed_outcomes.json --state-dir omni_state
python -m benfrank_omni calibrate --sport NBA --market points --state-dir omni_state
python -m benfrank_omni verify --run omni_runs/my_run
python -m benfrank_omni status
```

The outcome file is `{"outcomes":[...]}`. Each item requires `prop_id`, `sport`,
`player_id`, `market`, `event_id`, `completed:true`, `status:SETTLED|VOID`, the
observed `value` when settled, and `source_url`, `source_sha256`,
`retrieved_at_utc`. Results must be captured after the event starts. Settlement
inserts are append-only and identity-bound. Source provenance is retained;
uploaded results do not gain independent source verification.

Calibration reads only settled genuine `PREGAME` receipts from the same sport,
market, platform, scope, rule/scoring contract, engine version and code revision.
PUSH/VOID results are excluded from conditional nonpush calibration. Same-event
and same-start-time alternate lines remain on one side of the chronological
split. At least 100 training rows and 30 holdout events are required. It must
beat a constant training-rate baseline and avoid worsening raw Brier score or
log loss on the holdout. Holdout outcomes never fit the calibration bins.
The artifact can apply only after its actual creation time. Empty data produces
`INSUFFICIENT_GRADED_PREGAME_FORECASTS`, exit 2 and no active calibration model.
It never claims that replay tests establish a betting edge.

## Verify and deploy

```bash
python -m unittest discover -s tests -v
python scripts/omni_validate.py --mode software --output omni_runs/software
python scripts/omni_validate.py --mode live --output omni_runs/live
python scripts/omni_validate.py --mode export --output omni_runs/packages
```

The live validation uses actual fetched histories with **declared software test
lines**, not real bookmaker quotes. It performs historical held-out replays,
archives sources, and verifies 75,000 statistic draws per completed sample.
These are never advertised as predictions frozen before those historical games.

The OMNI Actions workflow uploads test logs, all receipts, charts, live-source
validation and 19 standalone sport runtime ZIPs, including partial failures.
Each exported package contains only its selected sport in the router catalog.
Model/data/calibration/ledger paths remain per sport. Credentials are not shared.
The repository integration lives on a development branch in the existing NBA
warehouse. Exporting packages does not claim that 18 additional repositories or
external prediction services have already been created or deployed. Original
warehouse data is not overwritten and existing certification gates remain.
