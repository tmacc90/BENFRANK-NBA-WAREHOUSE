# BENFRANK v5.3 — Core Probability and Failure-Path Contract

**Governing rule:** For the exact uploaded line, ask: *What needs to happen to cover, how likely is that path, and what could break it?* Evaluate OVER and UNDER with equal seriousness. No model can promise the highest hit rate before chronological forward measurement.

## Market-specific generative production

- **Points:** minutes → possessions/usage → shot volume/location and free throws → conditional make probability → points.
- **Rebounds:** minutes → opponent/team misses → accessible rebound chances and positioning → teammate competition → recoveries.
- **Assists:** minutes → touches and creation chances → potential assists → teammate shot conversion → assists.
- **Three-pointers:** minutes → three-point attempt volume and shot type → make probability → made threes.
- **Steals/blocks:** defensive possessions, relevant opportunities and event conversion; low-frequency count distributions.
- **Combinations (PRA and related):** model components jointly with possession-level dependence; never independently add marginal tail probabilities.
- **Fantasy Score:** joint box-score distribution and exact platform scoring formula; block when scoring contract is unknown.

Tracking availability is source- and game-specific. Missing tracking must be UNKNOWN, not estimated as an observed statistic.

## Early scenario engine

Keep v5.2 projected lineups as sufficient to forecast. Model base rotation, questionable teammate IN/OUT, restricted minutes, altered closing lineup, close game, blowout, foul trouble and overtime. Each scenario reports minutes, opportunity, conversion, expected stat, P(OVER), P(UNDER), PUSH/VOID, weight, weight provenance and reversal condition. Historical weights preferred; assumptions require explicit sensitivity ranges. Preserve team 240-minute conservation in regulation.

## Player DNA evidence

Use the 100-test source-gated bank and 60-question two-sided philosophy. For each applicable test, attach dated supporting AND contradicting game IDs, eligible sample size, opportunity/efficiency regime, upcoming relevance, source timestamp, missingness and confidence limitation. Avoid treating correlated tests or nested windows as independent votes. Separate **today's line replayed against historical outcomes** from historical actual wager-line snapshots.

## Matchup and similarity

Show player position/role, projected defender only when verified, opponent positional opportunity supply, pace, missed shots, rebound chances, potential assists, shot distribution, lineup-on/off and scheme provenance. Separate same-player analogues from same-role peer analogues. Match on pregame-observable features only. Show distance, features shared, exclusions, missingness and outcome at today's exact threshold. No inferred causal scheme claims without evidence.

## Five independent model families

1. Player/role hierarchical statistical distribution model with thin-sample shrinkage.
2. Machine-learning conditional distribution model.
3. Actual sequential possession and rotation simulator (retain 25K per supported prop and reproducible seeds).
4. Pregame-feature historical analogue model.
5. Isolated line-blind model that freezes its predictive distribution before the threshold is revealed.

Learn ensemble weights chronologically on held-out data; no equal voting, post-hoc winner selection or forced agreement. Shared data errors can affect all models.

## Failure-path prosecution

For each primary side, stress minutes, opportunity, conversion, teammate status, matchup assumptions, game script and ±0.5 line movement. Report the minimum plausible combination that reverses the side, probability of each scenario when supported, and the opposite-side historical case. More simulations reduce Monte Carlo noise, not misspecified input bias.

## Mandatory report panels

Exact prop and capture time; L5/L10/L15/L20/L25/L32/L52, current season, previous season and verified available career counts (OVER, UNDER, PUSH, eligible n, mean, median); mean/median/interval forecast; minutes and market-specific opportunity chart; positional matchup chart; same-player/peer similarity charts; OVER case; UNDER case; five-model disagreement; scenario reversal; source and sample-quality audit; final OVER/UNDER direction with separate research-only ticket eligibility; immutable receipt and postgame settlement.

A mean above the line does not imply P(OVER)>0.5. Derive side probabilities from the distribution, including push/void rules.

## Forward validation and release

Freeze forecasts before games. Measure all-prop and prespecified selected-subset hit rate with denominators and uncertainty, calibration curves, Brier score, log loss, market/timing segments, simple baseline comparisons, and selection rate. Use chronological train/calibration/test partitions and clustered uncertainty. Revisions append new versions; original predictions are never overwritten. v5.3 remains an unvalidated challenger until measured incremental out-of-sample benefit.

## First executable integration

`benfrank_v53_core.py` is an additive source-backed JSON report assembler using the v5.3 exact-line, DNA and same-player similarity modules. It explicitly marks unavailable peer comparisons, unsupported opportunity forecasts, and NO_TICKET. It does not replace v5.2's actual simulation pipeline or claim that all five model families, live source adapters, or full chart rendering are implemented.
