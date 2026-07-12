# Quartermaster documentation

**Quartermaster** is a self-hosted [MCP](https://modelcontextprotocol.io)
server (FastAPI + FastMCP) plus a Vue/Vuetify web UI. It serves versioned **AI
instruction kits** over an authenticated HTTP endpoint, so coding agents load
guidance on demand without the kit files ever being copied into a target
project.

This site collects the documentation for every audience. Pick the section that
matches what you are doing:

- **[Users](user/index.md)** — run Quartermaster locally, connect an agent to
  the MCP, and configure a repository against it.
- **[Developers](developer/index.md)** — work on the server and web UI: the
  architecture contract, local development, kit authoring, migrations, and the
  Python API reference.
- **[Operators](operator/index.md)** — deploy, observe, and release the
  hosted service.

The full version history is in the [Changelog](changelog.md).

```{toctree}
:hidden:
:maxdepth: 2

user/index
developer/index
operator/index
changelog
```
