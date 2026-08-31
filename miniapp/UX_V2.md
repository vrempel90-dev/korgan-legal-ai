# KORGAN Mini App UX v2

The Mini App now has one presentation owner: React (`src/main.jsx`) plus one consolidated responsive stylesheet (`src/ux-v2.css`).

The legacy presentation overlays are no longer loaded by `index.html`:

- `personal-lawyer.js`
- `client-safe-ui.js`
- `payment-auto-ui.js`
- `responsive.css`
- `ux-cleanup.css`
- `nav-cleanup.css`
- `korgan-brand.css`
- `korgan-site-typography.css`
- `personal-lawyer.css`
- `professional.css`

`document-access-ui.js` remains loaded only as a transport adapter because Telegram WebView needs native document download/access handling. It no longer uses `MutationObserver`, no longer creates buttons and never mutates or restyles visible UI nodes.

The legacy files remain in the repository for history, but only `src/ux-v2.css`, the React application and the non-visual document transport adapter are wired by the Mini App entry point.
