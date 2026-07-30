# The prompts catalog

Quartermaster also serves a **prompts catalog** — a separate library of
reusable Markdown instruction snippets, sibling to the kit catalog but much
simpler: a catalog prompt has no versions, no sections, and no
`applicability.json`. It is just a single Markdown file with an optional
`title`/`description` frontmatter block, written once and reused across every
project instead of being copy-pasted into each repo's `AGENTS.md`/`CLAUDE.md`.

## Catalog prompts vs. canned prompts

Quartermaster ships a small set of **canned prompts** — static templates
such as `trait_selection_bootstrap`, `greet`, and `integrate_project`,
fetched via `list_prompts` → `get_prompt`. Those are built into the server,
not user-editable, and unrelated to the catalog described on this page.

**Catalog prompts** are the opposite: content you or your team write,
discovered live from the catalog root(s), editable over REST, WebDAV, or the
MCP tools below. The two never collide silently — a catalog prompt cannot
take a name already used by a canned prompt; writing one is rejected
outright rather than creating an entry no client could ever reach.

## Using catalog prompts from an agent

Catalog prompts are exposed two ways, both reading the same live,
uncached catalog:

- **As native MCP prompts.** MCP-aware clients surface every catalog prompt
  as a user-invoked slash command / prompt-gallery entry. An edit is visible
  on the very next list — no cache, no server restart.
- **As MCP tools**, for an autonomous agent that wants the text directly:
  `list_catalog_prompts()` returns `{name, title, description, source_layer}`
  for every prompt visible to the caller; `get_catalog_prompt(name)` returns
  its full `{name, title, description, body}`.

## Writing your own prompts (private, via MCP tools)

Three tools manage your own prompts:

- `create_catalog_prompt(name, body, title="", description="")`
- `update_catalog_prompt(name, body, title="", description="")` (idempotent
  create-or-replace)
- `delete_catalog_prompt(name)` (idempotent)

The one rule to know: writes from these tools **always** land in your own
private overlay — never a shared or team layer, regardless of what an
operator has configured. This means a personal prompt library works with
*zero* operator setup, even on an instance with no shared prompts catalog
configured at all. Every one of these calls requires you to be
authenticated; an unauthenticated call is rejected.

## Authoring shared/team prompts (REST or WebDAV)

To publish a prompt the whole team should see, use the REST API or WebDAV
instead of the MCP tools — there is currently no web UI for prompt CRUD:

| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/api/prompts` | Merged view; creating requires the editor role. |
| `GET`/`PUT`/`DELETE` | `/api/prompts/{name}` | Read, replace, or delete in the merged view. |
| `GET` | `/api/prompts/layers` | List configured prompt layers. |
| `GET`/`POST` | `/api/prompts/layers/{layer_id}` | List or create within one layer. |
| `GET`/`PUT`/`DELETE` | `/api/prompts/layers/{layer_id}/{name}` | Read, replace, or delete in one layer (403 if that layer is readonly). |
| `GET`/`POST` | `/api/private-prompts` | Your own private prompts, over REST instead of MCP tools. |
| `GET`/`PUT`/`DELETE` | `/api/private-prompts/{name}` | Manage one of your own private prompts (404, not 403, on someone else's). |

Or mount `/dav` as a network drive and edit prompt `.md` files directly, the
same way you would author a kit.

## File format

```markdown
---
title: Short title
description: One-line description
---
The actual reusable instruction text goes here.
```

Frontmatter is optional; a body-only file with no `title`/`description` is
valid. Only `title` and `description` are recognized keys — any other key,
or a frontmatter block that never closes with a second `---`, is rejected
before anything is written.

## Layering (shared/team prompts)

A shared prompts catalog can be composed as ordered base → overlay layers,
using the same merge engine and `[[layer]]` TOML shape as
[kit layers](../developer/migrations/kit-layers.md) — see that page for the
full layer-file format and shadowing rules. Two things are different for
prompts:

- There is no "binding sections" concept — a prompt has no sections to bind,
  so a shadowed prompt name is simply replaced in full by the overlay.
- Unlike kits, a deployment with **zero** configured prompt layers is a
  valid, supported state: each user's private-overlay prompts still work
  with no shared catalog configured at all.

See [Operations](../operator/operations.md) for the `QM_PROMPTS_ROOT` /
`QM_PROMPT_LAYERS_FILE` / `QM_PRIVATE_PROMPTS_ROOT` environment variables.

## Errors you might see

`PromptNotFoundError` (404)
: No prompt with that name is visible to you.

`PromptConflictError` (409)
: The name already exists, or is reserved by a canned prompt.

`PromptValidationError` (422)
: Malformed frontmatter — an unclosed block, an unrecognized key, or content
  that would not round-trip back to what you sent.

`PromptLayerNotFoundError` (404)
: The requested layer id is not configured.

`PromptLayerReadonlyError` (403)
: The requested layer rejects writes.
