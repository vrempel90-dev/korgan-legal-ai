UX v2 intentionally removes the legacy presentation overlays from index.html:

- document-access-ui.js
- personal-lawyer.js
- client-safe-ui.js
- payment-auto-ui.js
- responsive.css
- ux-cleanup.css
- nav-cleanup.css
- korgan-brand.css
- korgan-site-typography.css
- personal-lawyer.css
- professional.css

The React app remains the single UI owner. UX behavior is consolidated in src/ux-v2.css. This note is documentation only; the legacy files remain in the repository for history and are no longer loaded by the Mini App entry point.
