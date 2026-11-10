# Graph Report - TwitchDropFarmer  (2026-11-10)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 802 nodes · 1826 edges · 45 communities (20 shown, 25 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 147 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9c8b98d1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 37
- Community 38
- Community 39
- Community 40

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 123 edges
2. `TwitchClient` - 115 edges
3. `DropCampaign` - 86 edges
4. `StreamCandidate` - 34 edges
5. `TestFarmEnginePipeline` - 31 edges
6. `_make_engine()` - 28 edges
7. `FarmEngine` - 26 edges
8. `_make_drops()` - 24 edges
9. `FarmDecision` - 19 edges
10. `MarkerListWidget` - 19 edges

## Surprising Connections (you probably didn't know these)
- `TestManualGameSelectionLogic` --uses--> `FarmDecision`  [INFERRED]
  tests/test_farm_pipeline.py → src/twitch_drop_farmer/models.py
- `TestDashboardIntegrityFallback` --uses--> `TwitchClient`  [INFERRED]
  tests/test_farm_pipeline.py → src/twitch_drop_farmer/twitch_client.py
- `TestFarmEnginePipeline` --uses--> `TwitchClient`  [INFERRED]
  tests/test_farm_pipeline.py → src/twitch_drop_farmer/twitch_client.py
- `TestFetchStreamsSlugResolution` --uses--> `TwitchClient`  [INFERRED]
  tests/test_farm_pipeline.py → src/twitch_drop_farmer/twitch_client.py
- `TestGQLWatchPayloadTypes` --uses--> `TwitchClient`  [INFERRED]
  tests/test_farm_pipeline.py → src/twitch_drop_farmer/twitch_client.py

## Import Cycles
- None detected.

## Communities (45 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (19): collect_cards(), on_result(), finish(), on_loaded(), on_timeout(), finish(), on_loaded(), on_timeout() (+11 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (5): DashboardGameCard, GameCard, worker(), worker(), _try()

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (3): FarmEngine, ProgressSnapshot, Watchdog

### Community 4 - "Community 4"
Cohesion: 0.13
Nodes (3): StreamCandidate, TestFetchStreamsSlugResolution, TestStreamCandidateEligibility

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (5): DiagnosticEngine, DiagnosticReport, DiagnosticResult, DiagnosticStatus, run_diag()

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (3): _inventory_campaign(), _make_engine(), TestSubscriptionFilterLogic

### Community 8 - "Community 8"
Cohesion: 0.10
Nodes (4): Alert, AlertManager, AlertSeverity, AlertType

### Community 9 - "Community 9"
Cohesion: 0.11
Nodes (8): get_alert_manager(), EnergyProfile, get_default_profile(), get_profile_by_name(), FarmSnapshot, ChannelOption, WatchdogConfig, WatchdogState

### Community 14 - "Community 14"
Cohesion: 0.09
Nodes (22): runs-on, steps, jobs, build-windows, name, on, push, workflow_dispatch (+14 more)

### Community 15 - "Community 15"
Cohesion: 0.11
Nodes (4): DropCampaign, TestCampaignExpiryGuard, _mock_fetch_streams(), TestDashboardIntegrityFallback

### Community 16 - "Community 16"
Cohesion: 0.16
Nodes (3): totals(), walk(), remaining_with_preconditions()

### Community 21 - "Community 21"
Cohesion: 0.18
Nodes (3): TestGQLWatchPayloadTypes, TestHeartbeatIntegration, _mock_fetch_streams()

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (4): main(), main(), run(), save_shot()

### Community 23 - "Community 23"
Cohesion: 0.21
Nodes (8): _dependency_help(), _install_hooks(), _thread_exc(), _unraisable(), _write(), main(), _qt_import_help(), run()

### Community 24 - "Community 24"
Cohesion: 0.16
Nodes (5): check_updates(), check_for_updates(), open_release_page(), parse_version(), VersionInfo

### Community 26 - "Community 26"
Cohesion: 0.14
Nodes (4): apply_update_and_restart(), _do_update(), download_release_zip(), UpdateManager

### Community 28 - "Community 28"
Cohesion: 0.18
Nodes (4): _browser_campaign(), _mock_fetch_streams(), _mock_fetch_streams(), _mock_fetch_streams()

### Community 33 - "Community 33"
Cohesion: 0.31
Nodes (4): AppConfig, load_config(), save_config(), _load_from_config()

### Community 35 - "Community 35"
Cohesion: 0.42
Nodes (6): _add_found(), _campaign_payload_from_node(), _extract_campaigns_from_json_blob(), _merge_found(), _normalize_game_payload(), _normalize_status()

### Community 37 - "Community 37"
Cohesion: 0.33
Nodes (3): enabled(), get_write_error(), log()

## Knowledge Gaps
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TwitchClient` connect `Community 11` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 9`, `Community 15`, `Community 16`, `Community 17`, `Community 20`, `Community 21`, `Community 25`, `Community 27`, `Community 32`, `Community 34`, `Community 35`, `Community 39`, `Community 40`, `Community 41`?**
  _High betweenness centrality (0.350) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `MainWindow` (e.g. with `AlertType` and `DiagnosticEngine`) actually correct?**
  _`MainWindow` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.08819345661450925 - nodes in this community are weakly interconnected._
- **Why does `MainWindow` connect `Community 2` to `Community 1`, `Community 3`, `Community 36`, `Community 5`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 13`, `Community 15`, `Community 17`, `Community 18`, `Community 22`, `Community 23`, `Community 31`?**
  _High betweenness centrality (0.273) - this node is a cross-community bridge._
- **Are the 15 inferred relationships involving `TwitchClient` (e.g. with `DiagnosticEngine` and `FarmEngine`) actually correct?**
  _`TwitchClient` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07057057057057058 - nodes in this community are weakly interconnected._
- **Why does `DropCampaign` connect `Community 15` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 16`, `Community 17`, `Community 18`, `Community 20`, `Community 25`, `Community 28`, `Community 29`, `Community 30`, `Community 39`, `Community 41`?**
  _High betweenness centrality (0.206) - this node is a cross-community bridge._