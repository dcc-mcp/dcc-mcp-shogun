# Changelog

## Unreleased

### Added

- Add typed, capability-gated official `Scene` object inspection, selection,
  and display-property tools.
- Add animation-range and playback controls from the official `Timeline`
  interface.
- Add ROM labeling, subject calibration, QuickPost, and expanded processing
  settings from the official `Offline` interface.

## [0.11.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.10.0...v0.11.0) (2026-08-24)


### Features

* add pipeline policy diagnostics ([#38](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/38)) ([51d2076](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/51d2076669130606aa67a6774f972a38c68539a5))
* add verifiable recovery receipt ([#39](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/39)) ([33fb881](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/33fb8815699ae32900d08a49d8fede1a6faa5cdb))
* define pipeline lifecycle receipts ([#37](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/37)) ([23a0949](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/23a09497d084bba17ad6122792da26e6d240fd6c))


### Bug Fixes

* harden sidecar liveness monitoring ([#40](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/40)) ([230c267](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/230c267e9392c8f374825e7c1fcf03905fcc4999))
* require an explicit pipeline ABI ([#41](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/41)) ([b73a11f](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/b73a11f0249b82676e1ca7ccbafde8214717e164))

## [0.10.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.9.0...v0.10.0) (2026-08-23)


### Features

* add Shogun install diagnostics ([#29](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/29)) ([8057b9d](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/8057b9d88a024211f903f5d98ede476172410d44))

## [0.9.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.8.4...v0.9.0) (2026-08-23)


### Features

* add allowlisted Shogun pipeline commands ([#27](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/27)) ([3252e8f](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/3252e8f6fafe7afa6e784abc376e7c5dbaef11a2))

## [0.8.4](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.8.3...v0.8.4) (2026-08-19)


### Bug Fixes

* avoid false Shogun host-exit detection ([1f14d10](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/1f14d10d849c0cdd1627577cdb0368df9c360413))

## [0.8.3](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.8.2...v0.8.3) (2026-08-19)


### Bug Fixes

* dispatch package publication after release creation ([#21](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/21)) ([9d5c246](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/9d5c246be509e093d05d4fc056e85d7ff2934f80))

## [0.8.2](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.8.1...v0.8.2) (2026-08-18)


### Bug Fixes

* harden Shogun control-stream startup ([a537562](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/a537562c31ed98d2c26eb7341f3d55c6c9658051))
* **sdk:** wait for the Shogun control stream and validate it with the SDK ([#18](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/18)) ([dd22206](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/dd22206a006c05a7ec570cd9ffc7ea3aa079c923))

## [0.8.1](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.8.0...v0.8.1) (2026-08-13)


### Bug Fixes

* **docs:** clarify Shogun blank-scene host states ([#16](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/16)) ([79d59bf](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/79d59bf302749b3581aff0359b1f3c5019b61c26))

## [0.8.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.7.0...v0.8.0) (2026-08-13)


### Features

* **scene:** add setup, rigid-body, and video-camera reads ([#14](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/14)) ([d376efe](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/d376efee7a61f90643eb1aa5983329c430b226d6))

## [0.7.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.6.0...v0.7.0) (2026-08-13)


### Features

* add verified Shogun production context updates ([#12](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/12)) ([be4620a](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/be4620af2f9a31012fff8d8476a21396ac271b64))

## [0.6.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.5.0...v0.6.0) (2026-08-13)


### Features

* add typed Shogun production context tools ([#10](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/10)) ([ca8f28c](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/ca8f28c04ad3688ac7f1d1769dd3121812e6da71))

## [0.5.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.4.0...v0.5.0) (2026-08-13)


### Features

* add typed Shogun data cleanup tools ([#8](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/8)) ([4239d9f](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/4239d9f3e88ee39f506e2c751dcef47d52b1e806))

## [0.4.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.3.0...v0.4.0) (2026-08-12)


### Features

* expand official Shogun SDK inspection ([#6](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/6)) ([fad70a1](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/fad70a18cada6dcef0b325315d2d6e911bd49d87))

## [0.3.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.2.0...v0.3.0) (2026-08-12)


### Features

* expand official Shogun SDK workflows ([#4](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/4)) ([92e49de](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/92e49de5208e5542d2489259509792dfd857a71b))

## [0.2.0](https://github.com/dcc-mcp/dcc-mcp-shogun/compare/v0.1.0...v0.2.0) (2026-08-12)


### Features

* add official Shogun timeline and processing workflows ([#3](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/3)) ([48aa765](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/48aa76563c69b7453664ca65727a633e9c461836))
* add Shogun brand and showcase assets ([af0901f](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/af0901fd1c615c7e128b2515eaf4c515e46eac91))
* add Vicon Shogun Post adapter ([2dc8767](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/2dc876723f38264644cf94f0380959ccf64f67ed))
* complete typed Shogun workflows ([#2](https://github.com/dcc-mcp/dcc-mcp-shogun/issues/2)) ([8cc0715](https://github.com/dcc-mcp/dcc-mcp-shogun/commit/8cc0715a61c572771b9145b0d1b10ac6ee0fdec6))
