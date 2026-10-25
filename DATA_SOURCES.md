# Data provenance and credits

Historical NBA Stats box scores and schedules: [SportsDataverse hoopR-nba-stats-data](https://github.com/sportsdataverse/hoopR-nba-stats-data). NBA game and player IDs are retained as strings. These are NBA-derived records mirrored by a third party, not a successful direct NBA endpoint fetch.

ESPN box scores: [SportsDataverse hoopR-nba-data](https://github.com/sportsdataverse/hoopR-nba-data), published in the [sportsdataverse-data player-box-score release](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_nba_player_boxscores). ESPN game/player IDs are stored separately and never presented as official NBA IDs.

The provider's repositories state [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) licensing. See [ESPN archive license](https://github.com/sportsdataverse/hoopR-nba-data/blob/main/LICENSE.md) and [NBA Stats archive license](https://github.com/sportsdataverse/hoopR-nba-stats-data/blob/main/LICENSE.md).

Changes made by BENFRANK: schema normalization, regular-season filtering, DNP exclusion, team-code normalization, accent/punctuation-only player-name matching, cross-source comparisons, and quarantine of disagreements. Sources do not endorse this framework.

`sources.json` contains exact source URLs, SHA-256 values, release asset identities, and the NBA-mirror Git commit. The saved SQLite database retains all input rows and source-file metadata, including excluded records. Data completeness and predictive validity are separate gates.
