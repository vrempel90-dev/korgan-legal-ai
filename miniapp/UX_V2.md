# KORGAN Mini App UX stability architecture

The goal is to preserve the current KORGAN visual identity while removing the architectural causes of UI regressions.

Visible UI is owned by React (`src/main.jsx`). The entrypoint also loads the existing presentation-only identity styles that define the current KORGAN look:

- `professional.css`
- `korgan-site-typography.css`
- `ux-cleanup.css`
- `korgan-brand.css`

`src/ux-v2.css` is now a stability layer only. It enforces responsive geometry, the current 2x2 home-card layout, four visible bottom-navigation tabs, fixed composer/nav spacing, payment input sizing and Telegram WebView repaint protection.

The following DOM-mutating presentation scripts are not loaded:

- `personal-lawyer.js`
- `client-safe-ui.js`
- `payment-auto-ui.js`

The following conflicting legacy presentation styles are not loaded:

- `responsive.css`
- `nav-cleanup.css`
- `personal-lawyer.css`

`document-access-ui.js` remains only as a transport adapter for Telegram document access/download. It does not use `MutationObserver`, does not create buttons, and does not insert, reorder or restyle visible UI nodes.

Important invariants:

1. React is the only owner of visible document action buttons.
2. The ready-document screen must never receive injected sibling buttons.
3. The bottom navigation is opaque and does not use `backdrop-filter`, preventing Telegram WebView flicker.
4. The composer is positioned above the bottom navigation using the same shared height.
5. Internal architecture/debug cards are not exposed to clients.
6. Production API, AI/legal pipeline, payments backend and Railway production services are outside this UX branch.
