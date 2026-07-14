# Migration guide: multi-root kit collections (layers)

This release adds **layered kit catalogs**: instead of a single catalog root,
Quartermaster can compose several named catalogs as an ordered stack
(base → overlay), e.g. a company-wide base plus a team-local overlay.

**You do not have to change anything.** A single `QM_KITS_ROOT` keeps working
exactly as before — it is treated internally as one layer named `default`,
and every URL (`/api/kits/...`, `/dav/...`) is unchanged. Read on only if you
want to opt into multiple layers.

---

## 1. What changed

- **New config:** `QM_KIT_LAYERS_FILE` (a TOML file) defines an ordered list
  of named layers.
- **Shadowing:** a kit name present in more than one layer is owned **entirely**
  by the highest-priority (last) layer that contains it — all of the base
  layer's versions of that kit are hidden.
- **Binding sections:** a base-layer section marked `binding = true` in its
  `index.toml` **always** appears in the merged kit, even when an overlay
  shadows that kit. Overlays cannot remove or replace a binding section.
- **Per-layer REST/WebDAV:** each layer is addressable by name at
  `/api/kits/layers/<name>/...` and `/dav/<name>/...`. The merged read views
  (`GET /api/kits`, `GET /api/kits/{name}`) are unchanged.
- **Read-only layers:** a layer can be marked `readonly = true`; REST/WebDAV
  writes to it are rejected with **HTTP 403**. The lock can also be applied
  per surface with `readonly_rest` / `readonly_webdav` (each defaults to
  `readonly`) — useful when a layer is synced from an external source (e.g.
  rsync from a pipeline) and one surface should stay writable.

Nothing is removed. `QM_KITS_ROOT` and the existing endpoints are fully
backward compatible.

---

## 2. Do I need to migrate?

| Your situation | Action |
|---|---|
| One catalog, happy with it | **None.** Keep `QM_KITS_ROOT`. |
| Want a shared base + local overlays | Switch to `QM_KIT_LAYERS_FILE` (§3). |
| Want some catalogs write-protected | Mark them `readonly = true` (§3). |

---

## 3. Opting into layers

Point `QM_KIT_LAYERS_FILE` at a TOML file. It is comment-friendly and
diff-reviewable, and **relative layer paths resolve against the file's own
directory** (not the process working directory), so a self-contained
`layers.toml` next to its catalogs is portable.

```toml
# /data/layers.toml — ordered base → overlay (first = lowest priority)

[[layer]]
name = "company"          # URL-safe; used in /api/kits/layers/company and /dav/company/
path = "company-kits"     # relative → /data/company-kits
readonly = true           # central base catalog: no writes from this server

[[layer]]
name = "synced"
path = "synced-kits"      # rsync'd from a pipeline: never author via WebDAV,
readonly_webdav = true    # but REST edits are still allowed (readonly_rest omitted → false)

[[layer]]
name = "team"
path = "team-kits"        # relative → /data/team-kits
# readonly omitted → writable (this is where /dav and REST writes land)
```

Per-surface keys (`readonly_rest`, `readonly_webdav`) each fall back to the
layer's master `readonly` when omitted, so `readonly = true` still locks both
surfaces. The REST surface covers **both** the web UI and programmatic `/api`
clients (they are enforced together); the web UI additionally hides its edit
controls for a REST-read-only kit.

```bash
docker run -d --name quartermaster -p 8000:8000 \
  -e QM_KEYCLOAK_URL=https://auth.example.com \
  -e QM_KEYCLOAK_REALM=quartermaster \
  -e QM_RESOURCE_BASE_URL=https://qm.example.com \
  -e QM_KIT_LAYERS_FILE=/data/layers.toml \
  -v qm-data:/data \
  -v /srv/company-kits:/data/company-kits \
  -v /srv/team-kits:/data/team-kits \
  ghcr.io/exhuma/quartermaster:stable
```

### Precedence

When both are set, `QM_KIT_LAYERS_FILE` (multi-root) takes precedence over
`QM_KITS_ROOT` (single-root):

```
QM_KIT_LAYERS_FILE  >  QM_KITS_ROOT
```

So you can leave `QM_KITS_ROOT` in place while testing a layers file, and
remove it once you're satisfied.

### Rules enforced at startup

- At least one kit source must be configured.
- At least one layer must be **writable** (not every layer can be
  `readonly = true`) — writes need somewhere to land.
- Layer `name`s must be unique.

A bad layers file fails fast at startup with a clear error rather than booting
into a half-configured state.

---

## 4. Layer ordering and shadowing semantics

Layers are listed **base → overlay**; the **last** layer wins. Given the
example above:

- A kit that exists only in `company` is served from `company`.
- A kit that exists only in `team` is served from `team`.
- A kit named in **both** is served entirely from `team` (the overlay) —
  including its version list. The `company` copy is hidden…
- …**except** any section `company` marks `binding = true`, which is merged
  into the served kit ahead of the overlay's own sections. (Binding base
  sections take an id-level precedence: an overlay section with the same id
  does not displace it.)

`source_layer` on each kit (visible via `GET /api/kits/{name}` and
`GET /api/kits/layers`) tells you which layer currently owns it.

### Binding sections (the `binding` flag)

By default, an overlay that shadows a kit replaces it **completely** — every
section the base layer defined for that kit disappears. A base layer can opt a
specific section out of that by marking it `binding = true` in its
`index.toml`. The name is literal: the section becomes **binding on the
overlays above it** — they inherit it and cannot drop or rewrite it.

```toml
[[sections]]
file = "policy.md"
title = "Company security policy"
gloss = "Non-negotiable security constraints from central engineering"
always_load = true
binding = true          # ← carries down the stack; overlays cannot remove or replace it
```

Precisely what `binding = true` does:

- **Survives shadowing.** When a higher-priority layer shadows the kit, every
  binding section from the lower (base) layers is still merged into the served
  kit, ahead of the overlay's own sections.
- **Cannot be overridden by id.** If an overlay declares a section with the
  **same id** (file stem) as a binding base section, the overlay's version does
  **not** win — the binding base section is the one served. (Non-binding base
  sections, by contrast, are fully replaced.)
- **Reads from the base layer.** A binding section's `title`, `gloss`, body,
  and `always_load`/`binding` flags all come from the layer that declared it,
  not the overlay.

What it does **not** do:

- It is **not** a lock on the base catalog itself — authors who can write to
  the base layer can still edit or remove the section there. `binding` governs
  what *overlays* may do, not who may write to the base. (To make a whole layer
  unwritable over REST/WebDAV, mark the **layer** `readonly = true`; see §3.)
- It has **no effect in a single-root (`QM_KITS_ROOT`) deployment** — with one
  layer there is nothing to shadow it, so the flag is simply inert.

`binding` defaults to `false`, so existing catalogs and single-root
deployments are completely unaffected. Use it sparingly: it is the mechanism
for a base layer to assert a **non-negotiable** section (a security policy, a
compliance rule, a mandated workflow) that downstream teams compose with but
cannot quietly override.

---

## 5. REST and WebDAV URL changes

The merged read API is unchanged. New, additive, layer-scoped routes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/kits/layers` | List configured layers (`name`, `path`, `readonly`, `rest_readonly`, `webdav_readonly`). |
| `GET` | `/api/kits/layers/{layer}` | List kits in one layer (un-merged). |
| `POST` | `/api/kits/layers/{layer}` | Create a kit in that layer (**403** if read-only). |
| `GET`/`DELETE` | `/api/kits/layers/{layer}/{name}` | Read / delete a kit in that layer. |
| `PUT`/`DELETE` | `/api/kits/layers/{layer}/{name}/versions/{v}/sections/{id}` | Section CRUD in that layer (**403** if read-only). |

WebDAV:

- **Single root (`QM_KITS_ROOT`):** still mounted at `/dav/` — unchanged.
- **Multiple layers:** each layer is mounted at **`/dav/{layer}/`**. If you
  mount the catalog as a drive, update your mount URL to include the layer
  name (e.g. `https://qm.example.com/dav/team/`).

---

## 6. Rolling back

Layers are purely a configuration concern; no catalog files are rewritten.
To revert, unset `QM_KIT_LAYERS_FILE` and keep (or restore) `QM_KITS_ROOT`.
The server returns to single-root behaviour with the original `/dav/` and
`/api/kits` URLs immediately on restart.
