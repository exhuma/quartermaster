# Connect your agent

Point a coding agent at a running Quartermaster instance so it can load
instruction kits for you. This takes two things, both from whoever runs the
instance:

- the **base URL** of the instance (for example `https://qm.example.com`), and
- a **credential** — either sign-in through the instance's identity provider,
  or a bearer token.

You do not need the Quartermaster source or a local build.

## The MCP endpoint

Kits are served over MCP (streamable HTTP) at:

```text
<base-url>/kits/mcp
```

for example `https://qm.example.com/kits/mcp`. Every request is authenticated —
there is no anonymous access.

## Authenticate

Pick whichever your client supports.

### Option A — sign in automatically (OAuth)

OAuth-aware clients (such as VS Code) discover the identity provider from the
instance and run a browser sign-in for you. Give the client only the MCP
endpoint URL; it handles the rest and refreshes tokens on its own. This is the
smoothest path when your client supports it.

### Option B — a bearer token

Clients that take a static header use a token issued by the instance's identity
provider. Ask your operator for a token (or for the client credentials to
request one), then pass it as an `Authorization` header. For example, with the
Claude Code CLI:

```bash
claude mcp add --transport http quartermaster \
  https://qm.example.com/kits/mcp \
  --header "Authorization: Bearer <token>"
```

## Verify

Ask the agent to call `resolve_kits` with a short description of the task you
are about to do, or call `list_kits` to see the catalog. A successful response
means the connection and credential are good.

## What happens next

Once connected, kit discovery is meant to be transparent: the agent calls
`resolve_kits` per task and loads the matching guidance without you managing it.
To make that reliable inside a repository, add the short briefing in
[Downstream agent guidance](downstream-agent-guidance.md). To confirm what the
agent actually loaded for a given task, see
[See what Quartermaster did](diagnostics.md).
