# Data provenance and credits

Historical NBA Stats box scores and schedules: [SportsDataverse hoopR-nba-stats-data](https://github.com/sportsdataverse/hoopR-nba-stats-data). NBA game and player IDs are retained as strings. These are NBA-derived records mirrored by a third party, not a successful direct NBA endpoint fetch.

ESPN box scores: [SportsDataverse hoopR-nba-data](https://github.com/sportsdataverse/hoopR-nba-data), published in the [sportsdataverse-data player-box-score release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_nba_player_boxscores). ESPN game/player IDs are stored separately and never presented as official NBA IDs.

The provider's repositories state [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) licensing. See [ESPN archive license](https://github.com/sportsdataverse/hoopR-nba-data/blob/main/LICENSE.md) and [NBA Stats archive license](https://github.com/sportsdataverse/hoopR-nba-stats-data/blob/main/LICENSE.md).

Changes made by BENFRANK: schema normalization, regular-season filtering, DNP exclusion, team-code normalization, accent/punctuation-only player-name matching, cross-source comparisons, and quarantine of disagreements. Sources do not endorse this framework.

`sources.json` contains exact source URLs, SHA-256 values, release asset identities, and the NBA-mirror Git commit. The saved SQLite database retains all input rows and source-file metadata, including excluded records. Data completeness and predictive validity are separate gates.

## Possession, lineup and WOWY reconstruction

BENFRANK uses the NBA public liveData CDN as the preferred game-level source for
play-by-play and box scores when available:

- `https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_<GAME_ID>.json`
- `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_<GAME_ID>.json`

The play-by-play action feed supplies period/clock/team/player events and a
possession-team field. The box score supplies official player identity, starter
flags and minutes. Raw responses are cached with SHA-256 provenance.

`stats.nba.com` PlayByPlayV3 and BoxScoreTraditionalV3 are fallback routes.
Historical NBA game IDs are taken from the existing pinned NBA Stats archive
inside reconciled player-game records; ESPN IDs are never substituted for NBA
game IDs.

Five-man stints are reconstructed from starters and substitutions. Every game
is reconciled to official player minutes before it can be used:

- <= 1% aggregate absolute minute error: FULL
- >1% and <=3%: FALLBACK
- >3%: QUARANTINED

Teammate WOWY, lineup samples and competitive closing-lineup evidence are
derived from the validated stints. They belong to the same correlated
lineup/role/opportunity evidence family and may not be counted as independent
confirmations by the decision tribunal.

