"""
HTTP routing layer (module-fastapi 3-layer architecture).

Routers are thin: they parse and validate requests, delegate to the
``app.services`` layer, and map domain exceptions to HTTP responses.
They contain no business logic and never touch the filesystem directly.

Populated from Phase 2 onward (kit CRUD admin API, integration page API).
"""
