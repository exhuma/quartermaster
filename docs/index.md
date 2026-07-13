# Quartermaster documentation

**Quartermaster** is a self-hosted [MCP](https://modelcontextprotocol.io)
server (FastAPI + FastMCP) plus a Vue/Vuetify web UI. It serves versioned **AI
instruction kits** over an authenticated HTTP endpoint, so coding agents load
guidance on demand without the kit files ever being copied into a target
project.

This site collects the documentation for every audience. Pick the section that
matches what you are doing:

- **[Users](user/index.md)** — use a running instance: connect an agent to the
  MCP and let it load kits, or author and evaluate the kits it serves.
- **[Developers](developer/index.md)** — work on the server and web UI from
  source: the architecture contract, local development, releasing, migrations,
  and the Python API reference.
- **[Operators](operator/index.md)** — deploy and observe the hosted service
  from the published container image.

The full version history is in the [Changelog](changelog.md).

```{toctree}
:hidden:
:maxdepth: 2

user/index
developer/index
operator/index
changelog
```
