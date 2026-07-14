# Migration guide: authorization (roles) and private kits

This release adds **authorization**. Two roles now exist — **`editor`**
(admin: edits the shared kit catalog and grants/revokes editor from others) and
**`consumer`** (read-only, the default). It also adds **private kits**:
standalone kits visible only to their owner.

:::{warning}
**Action required for existing deployments.** Writing to the shared
catalog now requires the **`editor`** role, and the default for every
authenticated user is **`consumer`** (read-only). Until you name at least one
editor via `QM_INITIAL_EDITORS`, **nobody can modify kits** through the REST
API or WebDAV. Reading kits over the MCP is unaffected.
:::

---

## 1. What changed

- **Roles:** an IdP subject (Keycloak `sub`) maps to `editor` or `consumer`.
  The mapping is a TOML file (default `server/var/roles.toml`, override with
  `QM_ROLE_STORE_PATH`). Unknown users default to `consumer`.
- **Write authorization:** every kit-mutating REST route (`POST/PUT/DELETE`
  under `/api/kits` and `/api/kits/layers/...`) and every **WebDAV write**
  method (`PUT`, `DELETE`, `MKCOL`, `MOVE`, `COPY`, `PROPPATCH`, `LOCK`) now
  requires the `editor` role → **HTTP 403** otherwise. Reads stay open to any
  authenticated user.
- **Bootstrap editors:** `QM_INITIAL_EDITORS` (a comma-separated list or JSON
  array of `sub`s) names editors seeded at startup. They **always** resolve to
  editor and **cannot be revoked** through the API, so an editor lockout is
  impossible.
- **New endpoints:** `GET /api/me` (`{sub, label, role}` — the SPA's role
  source of truth); `GET/PUT/DELETE /api/roles` (editor-only role admin);
  `GET/POST/GET|DELETE /api/private-kits...` (owner-scoped private-kit CRUD).
- **Private kits:** any authenticated user (consumers included — ownership, not
  role, is the gate) can author standalone kits under `QM_PRIVATE_KITS_ROOT`
  (default `server/var/private-kits/`). They are visible **only to the owner**,
  across `list_kits` / `select_kits` / `resolve_kits` / `get_kit` over the MCP,
  and never to anyone else (a non-owner read is a 404, not a 403).
- **Identity into MCP tools:** the authenticated caller's `sub` is now carried
  into FastMCP tool calls, which is what makes owner-only private-kit
  visibility work over the MCP.

Nothing is removed. The MCP read tools and every read endpoint are unchanged
for existing users.

---

## 2. Do I need to migrate?

| Your situation | Action |
|---|---|
| Consumers only ever read kits over the MCP | **None.** Reads are unaffected. |
| Someone edits kits via the web UI or WebDAV | **Required:** set `QM_INITIAL_EDITORS` to their `sub`(s) — see §3. |
| You mounted WebDAV with an app token before this release | Revoke and re-mint the token — see §4. |
| You want per-user private kits | Optional: set `QM_PRIVATE_KITS_ROOT` to a writable volume — see §5. |

---

## 3. Naming your editors (required to keep editing)

Set `QM_INITIAL_EDITORS` to the **stable Keycloak `sub`** of each admin. Roles
key on `sub` (immutable), not the username (which can change).

```bash
# Comma-separated (subjects are comma-free) …
QM_INITIAL_EDITORS="4f9c…-sub-a,7b21…-sub-b"
# … or a JSON array
QM_INITIAL_EDITORS='["4f9c…-sub-a","7b21…-sub-b"]'
```

Find a user's `sub` from `GET /api/me` while signed in as them, or from their
Keycloak user record. Bootstrap editors appear in `GET /api/roles` as
read-only `source: "bootstrap"` rows and can then grant `editor` to others from
the **Users** screen in the web UI (or `PUT /api/roles/{sub}`).

Persisted role grants live in `QM_ROLE_STORE_PATH` (default
`server/var/roles.toml`) — point it at a writable data volume in production so
grants survive restarts.

---

## 4. App-token identity change (WebDAV / metrics)

Previously the caller identity used the Keycloak `preferred_username`; it is now
the stable `sub`. App tokens minted **before** this release stored the username
as their owner, so their identity no longer matches the `sub`-keyed role
lookup. App tokens only grant WebDAV/metrics access (low blast radius), so:

- **Revoke and re-mint** any app tokens minted before upgrading (web UI →
  *Mount*, or `DELETE`/`POST /api/app-tokens`). New tokens bind to your `sub`.
- Existing token records are **not** rewritten automatically.

---

## 5. Enabling private kits (optional)

Point `QM_PRIVATE_KITS_ROOT` at a writable directory (default
`server/var/private-kits/`; use a mounted volume in production). Each owner's
kits live under a per-owner hashed subtree, isolated from the public catalog so
a missed enumeration path cannot leak them. Users manage theirs from the
**Private** screen in the web UI or the `/api/private-kits` API. No other user —
and no public MCP caller — can see them.

:::{important}
**Confidentiality note.** Private kits are stored **server-readable** (so the
server can resolve them). This protects visibility between users, **not**
against a server operator. True end-to-end encryption is deliberately out of
scope here; the trade-offs are analysed in
[`server/docs/research/private-kits-e2ee.md`](https://github.com/exhuma/quartermaster/blob/main/server/docs/research/private-kits-e2ee.md).
:::

---

## 6. New settings summary

| Env var | Default | Purpose |
|---|---|---|
| `QM_INITIAL_EDITORS` | *(empty)* | Bootstrap editor `sub`s; cannot be locked out. |
| `QM_ROLE_STORE_PATH` | `server/var/roles.toml` | TOML role mapping (`sub → role`). |
| `QM_PRIVATE_KITS_ROOT` | `server/var/private-kits/` | Per-owner private-kit catalog root. |

All three should point at writable, persistent volumes in production.
