"""
Business-logic layer (module-fastapi 3-layer architecture).

Services orchestrate rules and side effects. For kit mutations they
validate the proposed end-state (via the loaders in ``app.kits``) before
delegating durable writes to the ``app.storage`` layer, so the catalog can
never be left in a state that fails to load.

Populated from Phase 2 onward.
"""
