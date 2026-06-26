# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue
for a suspected vulnerability.

- Preferred: open a [GitHub security advisory][advisory] for this
  repository ("Report a vulnerability").
- Alternatively, email **exhuma@gmail.com** with the details.

Please include enough information to reproduce the issue (affected
version/commit, configuration, and steps). You can expect an initial
acknowledgement within a few days. Once a fix is available, we will
coordinate disclosure with you.

[advisory]: https://github.com/exhuma/quartermaster/security/advisories/new

## Scope

Quartermaster terminates authentication **inside the application**
(`JWTAuthMiddleware`), validating Keycloak-issued JWTs. Of particular
interest:

- Authentication / authorization bypass on `/api`, `/kits`, or `/dav`.
- The dev-only auth bypass (`QM_DEV_AUTH_ENABLED` / `QM_DEV_SHARED_SECRET`,
  `VITE_DEV_AUTH`) being reachable in a production build. Both flags must
  be unset in production; reports of this leaking are in scope.
- Path traversal or write-confinement escapes in the kit-write / WebDAV
  paths.

The kit catalog itself is supplied by operators and is out of scope.
