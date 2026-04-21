# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

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