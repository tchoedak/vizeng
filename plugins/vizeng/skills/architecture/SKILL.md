---
name: architecture
description: Design or reverse-engineer a project's architecture in a live, editable diagram the human and agent share, stored as JSON in the repo's .vizeng/ folder. Two modes - system design (pick and apply a named system-design method from a well-known practitioner) and model-native architecture (abstractions, roles, responsibilities and relationships optimized for LLM comprehension, with a geometry-free .model.md that agents read). Use when the user wants to design a new system, map or explain an existing codebase's architecture, define abstractions and their responsibilities, or review/edit an architecture diagram. Supports boxes, circles, text, notes, arrows (solid/dotted/thick), resize, zoom, fit, JSON and PNG export.
---

# vizeng:architecture

A diagramming workspace where the diagram is a shared file, not a picture.
You edit `.vizeng/<name>.json`; the human edits the same file in the browser; each side sees the other's changes within about a second.
Every saved diagram also has a `<name>.model.md` beside it: the same design with geometry stripped and relationships folded into each abstraction's card.
That file is what agents read later. The JSON is what the editor reads.

`SKILL_DIR` below is the directory containing this file.

## 1. Orient

Find the repo root (nearest `.git`); artifacts live in `<root>/.vizeng/`.
Read project instructions (AGENTS.md / CLAUDE.md), any existing `.vizeng/*.model.md`, and architecture docs the repo already has.
Decide the entry point:

- **New project**: little or no code. You design forward with the user.
- **Existing project**: learn the code first, draw what is there (status `current`), then propose changes (status `proposed`). Never draw an invented component as current.

Decide the mode from the request. If the user just says "run vizeng on this repo", do both: system first, then model-native.

| Mode | File | Kind | Reference |
| --- | --- | --- | --- |
| System design | `.vizeng/system.json` | `system` | [references/system-design.md](references/system-design.md) |
| Model-native architecture | `.vizeng/internals.json` | `model-native` | [references/model-native.md](references/model-native.md) |

Read the reference for the mode before drawing. The JSON format is in [references/format.md](references/format.md).
Large systems may use more files (`system-context.json`, `internals-ingest.json`); keep names `[a-z0-9-]`.

## 2. Start the editor

Start it once there is something to look at (after the first diagram JSON is written), not before a long stretch of code reading.
Run in the background, from the repo root:

```sh
python3 "$SKILL_DIR/scripts/vizeng.py" serve --repo . --name internals
```

It prints `URL http://127.0.0.1:<port>/?token=...` and writes the same URL to `.vizeng/.server.json` (gitignored).
Give the user that exact URL as a link, and try `open "<url>"` (macOS) - if the sandbox blocks it, tell the user to open it themselves.
The token is required; a URL without it shows an auth error.

**The server closes itself**, so sessions never leave orphaned processes:
after 10 minutes with no human interaction in the page and no write to `.vizeng/*.json`, or 60 seconds after the last tab closes.
Background polling from an open tab does not count as activity. The page warns in its last minute and shows a "session ended" banner after; nothing is lost because edits autosave.
So, every time you want the user to look at the diagram: if `.vizeng/.server.json` exists and its URL responds (`curl -s -o /dev/null -w '%{http_code}' "<url>"` gives 200), reuse it; otherwise start a new server and give the user the new URL.
Do not pass `--idle-minutes 0` (never close) unless the user asks for it.

## 3. Mode: system design

1. Establish constraints. For a new project ask only the questions that fork the design (typically: expected load and growth, consistency vs availability needs, team size, deployment target, budget). For an existing project derive them from code, config and infra files and state your assumptions.
2. Research briefly. If web search is available, spend a few searches on how comparable systems are built and on the candidate methods; if not, use the catalog in the reference and say research was offline.
3. Recommend one primary method (and at most one secondary lens) from the reference catalog - named after its practitioner - with a one-paragraph reason tied to this project's constraints. Do not hand over a menu. Record it in the document's `technique` field.
4. Apply the method's moves explicitly and draw the result: containers (services, workers, stores, queues, external systems) and the flows between them. Label every edge with what moves (data, protocol). Mark trust boundaries and failure points.
5. For an existing project, put real paths in each node's `card.paths` and mark anything you could not confirm in `card.notes`.

## 4. Mode: model-native architecture

This mode designs the internal abstractions - their roles, responsibilities, contracts and relationships - optimized for a model to reason about, not for human code-reading tradition.
Read [references/model-native.md](references/model-native.md) in full before drawing; it defines the role vocabulary, the card, the naming rules and the review checklist.

- **New project**: derive abstractions from the system design and the user's requirements. Write a card for each. Iterate with the user on the canvas.
- **Existing project**: inventory entry points, packages/modules, stores, external clients and composition roots. Map each to a card with `paths` and `tests`, using the code's real names. Then run the checklist and add proposed changes (renames, merges, splits, role fixes) as `proposed` nodes or as notes - keep the current map honest.

## 5. The edit loop

- Write JSON with your file tools. Omit `x`/`y` for new nodes - the editor auto-lays them out and saves positions back. Keep the `x`/`y`/`w`/`h` of existing nodes unless the user asked for a relayout.
- **Re-read the JSON before every edit**: the human may have changed it. Never write from a stale copy.
- After writing, run `python3 "$SKILL_DIR/scripts/vizeng.py" render --repo .` to validate and regenerate `.model.md`. Fix every `FAIL`; address `WARN`s.
- Yellow `note` shapes are the human's comments to you. When asked to look at the diagram, read the JSON (or `.model.md`, which lists them under "Open notes"), act on each note, then delete the addressed notes - or edit the note text to reply when you need an answer.
- When the human says they changed something, diff their version against what you last wrote and reflect the change in your understanding (and in code, if that is the task) rather than reverting it.

## 6. Finish

- Ask before adding a pointer to the project's AGENTS.md / CLAUDE.md, and show the exact text, e.g.:
  > Architecture: `.vizeng/internals.model.md` (model-native) and `.vizeng/system.model.md`. Read before changing module boundaries; when a change alters roles, responsibilities or relationships, update `.vizeng/*.json` via vizeng:architecture in the same change.
- `.vizeng/*.json` and `*.model.md` are meant to be committed. Do not commit unless asked.
- PNG: the user clicks **PNG** in the editor (downloads). If they want it in the repo, copy it into `.vizeng/`.
- If the user says they are done, stop the server (`kill <pid>` from `.vizeng/.server.json`); otherwise leave it - it closes itself.
- Report: the URL, files written, the method chosen and why, what you verified in code versus inferred, and open questions.
