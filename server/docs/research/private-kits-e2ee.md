# Securing Private Kits: E2EE and Remote-Sourcing (Research)

**Status:** exploratory. Not implemented. This document captures the design
space so we can return to it. The current implementation stores private kits
**server-readable** (see `app/private_kits.py`, `app/kits.py::_caller_layers`),
which is what lets server-side resolution keep working today.

## 1. Problem statement & threat model

Private kits can be highly valuable to their owners. The north-star goal is
**admin-proof** confidentiality: *not even a server administrator/operator with
disk and memory access could read a user's private kits.* That is true
end-to-end encryption (E2EE) — the server never holds the plaintext or the key.

Distinguish three threat tiers (each strictly stronger):

| Tier | Defends against | Server can read plaintext? |
|------|-----------------|----------------------------|
| T1 — At-rest | Stolen disk / backup / snapshot | Yes (in memory, transiently) |
| T2 — Transient | Stolen disk + casual operator | Yes (only during a request) |
| T3 — Admin-proof (E2EE) | Malicious admin, memory capture | **No, ever** |

The user's stated goal is **T3**. The rest of this document exists because T3
is fundamentally in tension with how Quartermaster resolves kits.

## 2. The core tension

Server-side resolution requires the server to **read kit content**:

- `app/resolver.py::resolve_kits` — infers traits from and ranks against kit
  text.
- `app/traits.py` — `load_vocabulary`, `build_trait_docs`, `build_section_refs`
  (reads section outlines), `catalog_fingerprint`.
- `app/embeddings.py` — embeds trait/section text.
- `app/kits.py` — `_catalog_entries`, `read_kit`, `read_kit_outline`.

Under true E2EE the server holds only ciphertext, so **none of these can run**
on private kits. T3 and server-side resolution are mutually exclusive for the
private subtree. Any admin-proof design must move resolution off the server (or
disable it) for private kits. This is the crux; every option below is a
different way of resolving that tension.

## 3. Options

### Option A — Client-side resolution (true E2EE, T3)

The server stores each private kit as an **opaque encrypted blob**. All
resolution for private kits happens on the client (or a trusted local agent)
that holds the key: fetch the owner's encrypted blobs, decrypt locally, run
trait inference + section ranking locally, and merge the result with the
server's public-kit recommendation.

- **What breaks server-side:** `_catalog_entries`, `resolver.resolve_kits`,
  `traits.*`, `embeddings.*` — none can see private plaintext. The MCP
  `resolve_kits`/`select_kits`/`get_kit` tools would return public results
  only; private results are computed client-side.
- **Cost:** re-implement (a subset of) the lexical/embedding ranker on the
  client; ship or bundle an embedding model client-side; lose server
  orchestration (sampling/elicitation) for private kits; larger client
  footprint; key management/custody on the client.
- **Value:** genuine admin-proofness. This is the only option that meets T3.
- **Design hook already in place:** the per-owner **self-contained** unit
  `{private_kits_root}/{hash(sub)}/{kit}/…` is exactly the granularity that can
  become one encrypted blob. `_caller_layers` is the single seam where private
  resolution would be disabled/redirected client-side.

### Option B — Envelope / at-rest encryption, server can decrypt (T1–T2)

Encrypt private kits at rest with a key the **server** controls (a KMS, an
age/sops key, or a per-user key wrapped by a server master key). The server
decrypts into memory to resolve, then discards.

- **Cost:** low. A thin encrypt-on-write / decrypt-on-read shim around
  `app/storage/kit_writes.py` and the private read path. Resolution is
  unchanged.
- **Value:** defeats stolen disks/backups (T1) and casual operators (T2). Does
  **not** meet T3 — a determined admin can read the key and memory.
- **Verdict:** good cheap hardening; a reasonable *near-term* step. Not the
  north star. Honestly label it as "encrypted at rest," never as E2EE.

### Option C — Remote OAuth sourcing (T2, middle ground)

Private kits live in a **user-controlled remote store** (their Git host, object
store, personal server). Quartermaster fetches them per-request using the
user's OAuth token, resolves in memory, and **never persists** them.

- **Cost:** medium-high. Remote fetch + caching policy (must not cache
  plaintext to disk), OAuth token custody/refresh, latency, availability
  coupling, provider-specific adapters.
- **Value:** the server never stores private plaintext; the user retains
  custody. But the server still sees plaintext transiently in memory (T2, not
  T3), so it is not admin-proof against memory capture.
- **Verdict:** attractive if users already keep kits in their own infra;
  complexity is real. Composes with Option B for the fetch cache.

## 4. Recommendation

| Option | Complexity | Value | Admin-proof (T3) |
|--------|-----------|-------|------------------|
| A — client-side resolution | High | High | **Yes** |
| B — at-rest encryption | Low | Medium | No |
| C — remote OAuth sourcing | Medium–High | Medium | No |

**Phased path:**

1. **Now (this package):** server-readable private kits. Correct visibility
   isolation (owner-only), full resolution. No confidentiality against the
   operator — documented, not hidden.
2. **Cheap hardening (opt-in):** Option B. Small, self-contained, resolution
   unaffected. Buys T1–T2.
3. **Only if T3 becomes a hard requirement:** Option A. Accept that private
   resolution moves client-side. Reuse the self-contained per-owner blob unit
   and the `_caller_layers` seam.

Do **not** ship Option B or C while calling it E2EE. If a truly simple T3
option ever appears, prefer it — but the analysis above suggests none exists
without moving resolution off the server.

## 5. Design hooks already in place (this package)

- **Self-contained owner unit:** `app/private_kits.py::private_root_for` →
  `{private_kits_root}/{sha256(sub)[:16]}/…`. One directory per owner, ready to
  become one encrypted blob.
- **Single resolution seam:** `app/kits.py::_caller_layers` decides whether a
  caller's private layer participates. This is where server-side resolution
  would be disabled/redirected for E2EE.
- **Cache isolation:** `catalog_fingerprint()`/`iter_catalog()` are
  public-only, so private content never enters the shared on-disk embedding
  cache — a precondition for later encrypting private content without
  invalidating public caches.
- **Identity plumbing:** `app/identity.py` + `app/mcp_identity.py` already carry
  the owner identity into the resolution path; a client-side variant would swap
  what happens *after* identity is known, not how it is obtained.
