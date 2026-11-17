# vizeng

Visual engineering skills for Claude Code and Codex. One plugin (`vizeng`), one skill so far: `vizeng:architecture`.

`vizeng:architecture` opens a local diagram editor that the human and agent share through `.vizeng/*.json` in the target repo.
Every diagram also gets a generated `<name>.model.md`: the same design without geometry, written for agents to read.

Modes:
- **System design** - pick one named method (Kleppmann, Kreps, Dean, Vogels, Helland, Evans, Fowler/Newman, Xu, Lampson, Armstrong) and apply it.
- **Model-native architecture** - abstractions, roles, responsibilities and relationships optimized for LLM comprehension. See `plugins/vizeng/skills/architecture/references/model-native.md`.

## Server lifetime

Editor servers close themselves, so agent sessions never leave orphans:
- 10 minutes with no human interaction in the page and no write to `.vizeng/*.json` (`--idle-minutes`, 0 = never). An open but untouched tab does not count.
- 60s after the last tab closes (pagehide beacon). A crashed browser is detected after 3 minutes of silence.
- SIGTERM exits cleanly. Every exit removes `.vizeng/.server.json`.

## Layout

```
.claude-plugin/marketplace.json        Claude marketplace  -> plugins/vizeng
.agents/plugins/marketplace.json       Codex marketplace   -> plugins/vizeng
plugins/vizeng/.claude-plugin/plugin.json
plugins/vizeng/.codex-plugin/plugin.json
plugins/vizeng/skills/architecture/    SKILL.md, references/, scripts/vizeng.py, assets/app.html
tests/                                 unit tests + headless-browser E2E
```

## Install

Requires Python 3.8+ (stdlib only) and a browser.

Claude Code:

```sh
claude plugin marketplace add tchoedak/vizeng
claude plugin install vizeng@vizeng
```

Codex:

```sh
codex plugin marketplace add tchoedak/vizeng
codex plugin add vizeng@vizeng
```

Then ask your agent to diagram the system design or internal architecture of a repo, or invoke `vizeng:architecture` directly.

## Develop

```sh
./install.sh   # installs this checkout into ~/.claude, ~/.codex and any ~/.claude-* / ~/.codex-* profiles
```

Both harnesses cache installed plugins by version. After editing the skill, bump `version` in both `plugin.json` files and re-run `./install.sh`.
Override the target dirs with `CLAUDE_DIRS` / `CODEX_DIRS` (space-separated).

## License

[MIT](LICENSE)

## Test

```sh
python3 -m unittest discover tests        # server, validation, model view, CLI

# E2E: start a server on a scratch repo containing .vizeng/internals.json, then
VIZENG_URL=<printed URL> VIZENG_DIR=<repo>/.vizeng OUT=<dir> python3 tests/e2e_browser.py

python3 tests/e2e_lifecycle.py [screenshot-dir]   # auto-close; starts its own servers
python3 tests/e2e_layout.py [screenshot-dir]      # legibility: label/shape/line overlaps, crossings, grouping
```

The E2E drives headless Chromium (Python Playwright). On macOS it cannot launch inside the Claude Code sandbox.
