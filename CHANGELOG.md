# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

## [1.2.0] - 2026-04-22

### Added

- Dashboard status coverage for subscription-required and lost campaigns (full and partial), including dedicated badges, ribbons, and tooltips.
- Campaign model flags for `all_drops_claimed` and `requires_subscription` to improve decision quality and UI signaling.
- Search fields and bulk selection actions in filter lists, with tab-level selected/total counters.
- New translated UI labels and reason messages for the expanded dashboard and filtering flows.

### Changed

- Campaign stream selection now tolerates inconsistent ACL channel labels by falling back to drops-enabled streams when needed.
- Active target presentation prefers displayable active decisions, improving dashboard and farming panel continuity.
- Dashboard completion logic now better distinguishes completed, upcoming, offline, subscription-required, and expired-lost states.
- Filter section layout moved to sub-tabs for cleaner left-side navigation and reduced scrolling.

### Fixed

- Prevented subscription-only campaigns from being treated as farmable watch-time targets.
- Corrected account-link fallback parsing for campaigns missing explicit `self` connection payloads.
- Improved channel login extraction from nested ACL payloads using stricter token validation.

### Release Notes

- PT: [docs/releases/v1.2.0.pt-PT.md](docs/releases/v1.2.0.pt-PT.md)
- EN: [docs/releases/v1.2.0.en.md](docs/releases/v1.2.0.en.md)

## [1.1.0] - 2026-04-21

### Added

- Asynchronous game artwork loading in the dashboard and farming view.
- Prioritized image fallback flow using Twitch, Steam, and Google Images.
- Generated game cover placeholders with initials when no real artwork is available.
- Manual dashboard refresh action to clear image caches and reload the current snapshot.
- Release notes in [docs/releases/v1.1.0.pt-PT.md](docs/releases/v1.1.0.pt-PT.md) and [docs/releases/v1.1.0.en.md](docs/releases/v1.1.0.en.md).

### Changed

- Increased the live refresh timer interval to reduce unnecessary churn.
- Improved campaign completion handling for edge cases where Twitch leaves finished campaigns marked active.

### Fixed

- Total timeout handling across GraphQL retry profiles.
- Safer timestamp parsing for malformed Twitch responses.
- Proper Qt browser fallback cleanup.
- Retry behaviour for failed artwork resolution by avoiding permanent empty-cache entries.
- Validation of Steam library artwork URLs before use.

## [1.0.0] - 2026-04-21

- Initial public release tag and documentation refresh.