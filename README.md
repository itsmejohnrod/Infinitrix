ARCADE UPDATE: Read INSTALL_ARCADE.txt and THIRD_PARTY_GAMES.md first.

# Infinitrix: third-party API edition

Our games. Yours to play.

## Update your existing installation

1. Stop the Python server with Ctrl+C.
2. Make a backup copy of your current Infinitrix folder.
3. Extract this archive elsewhere, then copy the contents of its Infinitrix folder into your existing Infinitrix folder. Replace matching source files.
4. KEEP your existing `.env`, `.venv`, and entire `instance` folder. This archive excludes them, so your account database is not replaced.
5. In Git Bash inside your existing project:

```bash
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m uvicorn app:create_app --factory --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 on the computer. On your phone, use your computer's LAN IP on the same private Wi-Fi. Refresh the browser; if old game names appear, reload without cache or clear this site's cached files. Do not clear cookies unless you are happy to log in again.

Accounts, preferences, authentication, and email/Google configuration are unchanged. New game records use the existing database schema. Retired game records remain in SQLite but are excluded from the revised dashboard and rankings. Old Memory results are also excluded from the revised Card Memory rankings.

## Five actual third-party integrations

| Game | Provider | Essential external input | Scoring |
|---|---|---|---|
| Sudoku | Dosuku | Board, solution, difficulty | Less completion time |
| Card Memory | Deck of Cards API | Six randomly drawn card identities | Fewer moves |
| Word Detective | Free Dictionary API | Definitions for three word clues | Correct answers of 3 |
| Trivia Challenge | Open Trivia DB | Ten questions and answer choices | Correct answers of 10 |
| Guess the Pokémon | PokéAPI | Identities and sprites, three questions | Correct answers of 3 |

The application creates the interface and game rules. These APIs provide data essential to every new round. They are not iframe games. The UI names and links the provider during play. New rounds have no silent local-content fallback: provider failures show an error. Once a round has loaded, subsequent actions use its stored server-side data.

All game actions and answer checks go through our Python API. Answers, memory card layout, and Sudoku solution are kept on the server until required for play or feedback. Round IDs are account-bound and save once. Memory mismatches wait for Continue. Trivia and guessing rounds wait for Next. No flashing or reveal animation is used. Sudoku supports numeric mobile keyboards.

Pokémon sprites are normal images returned by the provider, not animated GIFs. The four Pokémon choices are reused over three questions per round, so later questions may be easier by elimination. Word clues use a small curated word pool; definitions themselves are fetched externally. Sudoku uses provider-assigned difficulty; mixed-difficulty time rankings are casual rather than normalized competitive rankings.

## Endpoints for documentation

- Cards: `https://deckofcardsapi.com/api/deck/new/draw/?count=6`
- Sudoku: `https://sudoku-api.vercel.app/api/dosuku`
- Dictionary: `https://api.dictionaryapi.dev/api/v2/entries/en/{word}`
- Trivia: `https://opentdb.com/api.php?amount=10&type=multiple`
- Pokémon: `https://pokeapi.co/api/v2/pokemon/{id}`

Provider documentation/source:

- https://github.com/crobertsbmw/deckofcards and https://deckofcardsapi.com/
- https://sudoku-api.vercel.app/ (Dosuku by Raghav Gupta)
- https://github.com/meetDeveloper/freeDictionaryAPI and https://dictionaryapi.dev/
- https://opentdb.com/api_config.php
- https://github.com/PokeAPI/pokeapi and https://pokeapi.co/docs/v2

Open Trivia DB data is CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/ . Dictionary response data may contain source/license metadata; its repository's code license is not automatically the license for all definitions. Pokémon names and artwork retain their respective owners' rights. Preserve source attribution and check provider terms before public use. No claim of affiliation with Pokémon's owners is made.

## Run tests

```bash
python -m unittest discover -s tests -p test_external.py -v
```

These tests mock provider responses and check all five integrations, server-side scoring, duplicate submissions, hidden solutions, and provider outages. Old tests from the first edition target retired endpoints and should not be used for this edition.

Live providers and the real PyScript browser runtime could not be validated in the build environment because external connections and Chromium execution were restricted. The implementation is ready for local integration testing, not certified live availability. Start each game locally to verify all five providers; send the exact on-screen error if any provider fails. Provider speed, schemas, availability, rate limits, and licensing can change.

## Fresh installation

Use Python 3.11+, create a virtual environment, install requirements, copy `.env.example` to `.env`, and run `python app.py`. The first account's verification code is in `instance/mailbox.log` in local console email mode. Real SMTP and Google OAuth still require your own credentials. Never commit `.env`, local mail logs, or the SQLite database.

The app remains a student project: persistent SQLite storage, HTTPS, real mail, configured Google callbacks, and completed operator/contact/legal disclosures are needed before public hosting. The profile uses a first-letter avatar. PyScript 2026.7.3 downloads from pyscript.net and its runtime CDN on the first Games visit.
