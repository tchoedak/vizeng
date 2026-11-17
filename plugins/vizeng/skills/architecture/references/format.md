# .vizeng JSON format (v1)

```json
{
  "vizeng": 1,
  "kind": "model-native",
  "title": "Filings pipeline internals",
  "summary": "optional one-paragraph overview",
  "technique": {"name": "Data-intensive design (Kleppmann)", "why": "..."},
  "nodes": [
    {
      "id": "filing-source",
      "shape": "box",
      "label": "FilingSource",
      "color": "blue",
      "status": "current",
      "group": "ingest",
      "x": 0, "y": 0, "w": 210, "h": 100,
      "card": {
        "role": "Source",
        "purpose": "Pull new SEC filings since the last cursor.",
        "owns": ["edgar cursor"],
        "does": ["poll EDGAR", "decode filings into RawItem"],
        "never": ["classify", "dedupe"],
        "out": "RawItem",
        "effects": ["HTTP to sec.gov"],
        "fails": ["HTTP 429 -> backoff, surfaced as SourceStalled after 5 tries"],
        "paths": ["src/sources/edgar.py"],
        "tests": ["tests/test_edgar.py"]
      }
    },
    {"id": "n-note-1", "shape": "note", "label": "Should this also own the RSS cursor?"}
  ],
  "edges": [
    {"id": "e1", "from": "filing-source", "to": "dedup-gate", "rel": "emits", "label": "RawItem",
     "style": "solid", "weight": "thick", "arrow": "end"}
  ]
}
```

Rules (enforced by `vizeng.py render` and the server):

- `kind`: `system` or `model-native`.
- Node `id`: unique, stable; prefer readable kebab ids for nodes you create. `shape`: `box` (default), `circle`, `text`, `note`.
- `x`, `y`, `w`, `h`: optional. Missing positions are auto-laid out by the editor and saved back: a fresh diagram gets a layered layout that minimizes crossings; nodes added to an arranged diagram go next to what they connect to, without moving anything else.
- `group`: optional short string (`"ingest"`, `"storage"`). Nodes sharing a group are laid out next to each other and listed with it in the model view. Give every node a group when the diagram has more than ~8 nodes.
- `color`: `default`, `blue`, `green`, `amber`, `red`, `purple`, `gray`. `status`: `current` (default) or `proposed` (drawn dashed).
- In `model-native`, every box/circle needs `card.role` from the role table. List fields (`owns`, `does`, `never`, `effects`, `fails`, `invariants`, `paths`, `tests`) are arrays of strings; `purpose`, `in`, `out`, `notes` are strings.
- In `system`, cards are lighter: `purpose`, `tech`, `paths`, `notes`.
- Edge `from`/`to` must reference node ids. `style`: `solid`|`dotted`. `weight`: `normal`|`thick`. `arrow`: `end`|`both`|`none`. `rel` is the relationship verb (model-native); `label` is what flows.
- Edge `label`: at most 40 characters (a `WARN` otherwise), ideally 1-4 words - a type name (`RawItem`), a payload (`cursor`), a rate (`5k/s`). The canvas wraps labels to two short lines and cuts the rest; a sentence also crowds neighboring edges. Explanations belong in the card (`out`, `does`, `effects`) or a note.
- Edges are routed around shapes and labels placed clear of shapes, labels and lines automatically. Don't add `text` nodes or waypoints to fix layout; if a diagram is still crowded, the fix is fewer edges (drop ones the cards already imply) or a split into two diagrams.
- `text` nodes are free-standing labels; `note` nodes are human-to-agent comments and are excluded from the abstraction list.
- Keys starting with `_` are dropped on save.
- `<name>.model.md` is generated. Never edit it.
