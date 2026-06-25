// Local-dev stub. Leaves the runtime config empty so src/config.ts uses
// the build-time VITE_* fallback during `npm run dev`.
//
// In PRODUCTION this file is NOT used: the FastAPI server serves a
// dynamically-rendered /config.js (window.__APP_CONFIG__ from its env)
// which takes precedence over this static stub. See server/app/webui.py.
window.__APP_CONFIG__ = window.__APP_CONFIG__ || {}
