# Context Engine

CLE never dumps a whole repository at the model. It retrieves a small, ranked,
provenance-tagged set of snippets relevant to the request.

## Three retrieval modes

| Mode        | Backend                         | Command        |
|-------------|---------------------------------|----------------|
| Exact       | ripgrep (Python fallback)       | `cle search`   |
| Structural  | symbol index (SQLite)           | `cle symbol`   |
| Semantic    | local embeddings + cosine       | (used by retrieve; built via `cle embed`) |

- **Exact** — literal/regex text search. Always available offline; respects
  vendor/build excludes.
- **Structural** — look up classes/methods/fields/etc. by name from the index
  built by `cle index`.
- **Semantic** — embed source chunks with the configured `embedding` model and
  rank by cosine similarity. Requires `cle embed` (which needs an embedding
  model + Ollama). Degrades gracefully to structural-only when unavailable.

## Pipeline

```
User request
  ↓ tokenize → identifiers
Structural retrieval   (symbols whose name matches a query token)
  ↓
Semantic retrieval     (top-k similar chunks, if embeddings built)
  ↓
Merge + de-duplicate (by file:line)
  ↓
Rank by relevance
  ↓
Budget (context.max_files / context.max_tokens)
  ↓
Context block → model
```

## Provenance (every item carries)

Each `ContextItem` retains:

- `path`, `line_start`, `line_end` — exact location (`file:line-line`)
- `symbol`, `kind` — what it is (e.g. method `login`)
- `relevance` — score used for ranking
- `reason` — why it was selected (e.g. *"symbol 'login' (method) matches query token"* or *"semantic similarity 0.82"*)
- `source` — evidence class, always `LOCAL` for project code

The context block shown to the model includes `source=` and `reason=` on every
snippet so answers can cite `file:line`.

## Evidence model

Sources are classified `LOCAL | CACHED | LIVE` and **never upgraded** — LOCAL or
CACHED can never be relabelled LIVE (`cle/evidence.py`, enforced by
`assert_no_upgrade`). Project retrieval is always LOCAL.

## Budget

`context.max_tokens` (approx chars = tokens × 4) and `context.max_files` bound
the assembled context — sized conservatively for 8 GB VRAM.

## Commands

```bash
cle search "driver initialization"     # exact
cle search -i -F "Thread.sleep("       # case-insensitive, literal
cle symbol WiniumDriver                # structural
cle explain src/main/java/LoginPage.java   # reasoning model + symbol outline
cle embed                              # build semantic index (needs embedding model)
```
