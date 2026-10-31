# BENFRANK v5.3 DNA + Matchup Similarity Challenger

Additive to the v5.2 EARLY_PREGAME branch, not a replacement for the 66-stage governing contract. This is a research-only challenger; preserve immutable v5.2 forecasts, ledger, 25K full-game simulator, 2K scenario stresses, independent line-blind Blind worker and NO_TICKET gates.

## Required report layout

1. Exact uploaded line, capture timestamp (UNKNOWN when unavailable), analysis cutoff, game, team, opponent, market, scoring contract and source hashes.
2. Actual historical OVER / UNDER / PUSH counts and denominators for L5/L10/L15/L20/L25/L32/L52, current season, previous season, and **available career**. Include mean/median and game IDs; do not imply the available archive is a complete career. DNP and unavailable logs are not UNDER.
3. Projection chart: uploaded line, expected stat, primary mean/median and uncertainty, independent Blind expectation, low/base/high minutes scenarios. Display numbers only from actual receipts.
4. Player DNA checklist: ten families of ten predeclared tests (100 total), each with observed source feature, game IDs, support, conditional OVER/UNDER counts, uncertainty, applicability, and reason why missing. Do not treat 100 correlated checks as 100 independent votes.
5. Matchup chart: upcoming opponent's positional opportunities, minutes, pace, usage, expected missed shots, rebound chances, potential assists, shot profile, defensive scheme and on/off teammate splits. Compare to player's own historical opponents and **separately** to same-role peer analogues. No invented defender assignments, tracking stats or college translation.
6. Similarity chart: rank actual earlier game IDs by predeclared, normalized feature distance; show shared feature count, source tier, opponent, role, exact-line outcome and missingness. Use historical as-of features, not the target game's observed outcome as a matching feature. Distinguish same-player analogues from peer cohorts and report effective sample size.
7. Reverse Prosecutor: strongest UNDER case against an OVER and strongest OVER case against an UNDER; identify scenario reversals, correlated evidence, small-sample bias and opponent-adjustment uncertainty.
8. Primary 25K actual sequential games, separate 2K downside/upside stress, line-blind pooled model, provenance, void/push counts, disagreements, calibration scope, research-only release and immutable settlement receipt.

## Executable first slice

`benfrank_v53_dna.py` provides exact-line counts, a 100-test schema with source-gated descriptive conditional checks, and transparent same-player nearest-game matching. This is **not yet wired into** the v5.2 pipeline, does not implement peer matching or real matchup data acquisition, and must not be labeled a completed end-to-end v5.3 run. Its `opponent_positional_allowance` feature is optional and only usable when present in dated source records. Future integration must enforce source timestamps and audit season/career coverage, verify positional assignments, apply hierarchical shrinkage and run held-out incremental-value tests before giving these checks model weight.

The 100 tests are candidate analyses, not 100 guaranteed causal reasons. Some are not available for all markets; show UNAVAILABLE, never a fabricated result. Nested L5/L10 windows overlap and must not be multiplied as independent evidence.

## Next acceptance tests

- Real warehouse adapter maps every stat and market, including platform-specific fantasy score contracts.
- As-of matchup features and peer-role matching with pregame-only opponent features.
- Chronological out-of-sample comparison: v5.2 champion vs v5.3 challenger on identical frozen props, with game-cluster confidence intervals and market-specific calibration.
- Rendering and persistence of chart data and every evidence receipt, including missingness and sample-size flags.
- Preserve all old predictions; never retrospectively replace them with v5.3 results.
