"""
Storage layer (module-fastapi 3-layer architecture).

The read half of kit storage currently lives in ``app.kits`` (discovery,
index/manifest parsing, content reads). The write half — atomic,
path-confined filesystem mutations — is added here from Phase 2 onward.
This layer performs filesystem effects only; it holds no business logic.
"""
