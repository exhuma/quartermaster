# Developers

Working on the Quartermaster server and web UI.

- **[Development](development.md)** — run the backend, web UI, and test suites
  locally.
- **[Contract](contract.md)** — the cross-cutting contract for the server and
  SPA; consult it before making changes.
- **[Releasing](releasing.md)** — the CalVer-tag-driven release process and
  cascading channel pointers.
- **[Migrations](migrations/authorization.md)** — upgrade guides for
  authorization/roles and layered kit catalogs.
- **[Python API reference](api/index.md)** — autodoc for the backend modules.

Authoring and evaluating the kits Quartermaster serves are user tasks, not
server-development ones — see [Authoring kits](../user/authoring-kits.md) and
[Evaluating kits](../user/evaluating-kits.md).

```{toctree}
:hidden:
:maxdepth: 1

development
contract
releasing
migrations/authorization
migrations/kit-layers
api/index
```
