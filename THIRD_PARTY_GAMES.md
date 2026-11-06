# Infinitrix arcade additions

Integration prepared 6 November 2026. These are third-party HTML5 source games, separate from the five API integrations. They do not submit scores to the API-game leaderboard.

## Clumsy Bird
Source: https://github.com/ellisonleao/clumsy-bird
Author: Ellison Leão. Code: GPL version 3; full text retained in static/vendor/bird/LICENSE.md. Engine: bundled melonJS 4.0.0, MIT notices retained. Upstream art, fonts, music and effects are included unchanged with the supplied project. The archive does not contain a separate comprehensive attribution list for every media file; no independent verification of media provenance was performed.

Readable corresponding game source is included in static/vendor/bird/js. The unused prebuilt bundle was omitted; index.html loads the readable source files in upstream Grunt build order. Full upstream README, customizing notes and developer credits are retained. Modified files: index.html, host.css, host.js, js/game.js, js/entities/entities.js, js/screens/play.js, js/screens/gameover.js. Changes: explicit launch, sound controls, readiness signal, removal of collision flash and vibration, removal of unused undefined-score measurement, removal of automatic volume override.

## Pixel Platformer
Source: https://github.com/melonjs/tutorial-platformer
Included: tutorial_step8 only. This is an educational platformer demo, not a full commercial campaign.
Code contributors include Olivier Biot and Jason Oster. MIT text retained in static/vendor/platformer/MIT-LICENSE. Tile-art gfxlib-fuzed license retained in data/img/map/license.txt (Common Public License text; do not label all assets MIT). Press Start font: Cody Boisclair, SIL OFL 1.1; notice retained in data/fnt/LICENSE.txt and static/fonts/PressStart2P-LICENSE.txt. Upstream music file is named dst-inertexponent. Retained media lacks a comprehensive separate attribution inventory in the supplied archive.

Modified files: index.html, host.css, host.js, js/game.js, js/entities/entities.js. Changes: launch under user control, readiness signal, sound toggle, touch movement/jump controls, key release on blur/cancel, removal of hit flicker. Other runtime source and assets retained. Engine loads from the upstream melonJS v13 jsDelivr URL. This remote engine was not downloadable in the build environment and is not bundled. The platformer needs internet access to cdn.jsdelivr.net; explicit error feedback appears if it fails. The upstream major-version URL remains unchanged.

## Advertising and navigation review
No advertising SDK or external-navigation calls were found in the active game-specific source. The replacement HTML pages contain no outgoing links. Metadata/social tags from the bird HTML were removed. The bird build uses its bundled engine; platformer uses the engine CDN. Upstream README and license links remain in source documents for attribution, not gameplay buttons.

Frames omit popup and top-navigation sandbox permissions. Game responses allow framing only by the same origin; CSP restricts resource loading to local files and the required engine CDN. Frames use allow-same-origin for engine/local-storage compatibility and are for the inspected trusted code; they are not an isolation boundary against arbitrary malicious code hosted on the same origin. The local sources contain no intended redirect. Runtime behavior was not browser-verified here; the external platformer engine is outside the inspected archive.

## Verification
Nine automated tests pass: existing six API-game tests plus three integration tests covering frame headers, HTML asset serving, map image references, and absence of navigation/ad patterns in game-specific scripts. Python and JavaScript syntax checks pass.
Browser rendering, gameplay, audio output, fullscreen, mobile layout and multi-touch are NOT verified: Chromium could not launch in this environment. These need local testing. Existing API provider tests use mocked responses, not live services.
