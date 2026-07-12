# tuckit

## Design tokens

Four static CSS files under `tuckit/web/static/web/`, linked in this order:
`tokens.brand.css` (shared, DO NOT hand-edit without running the landing sync
script) → `tokens.product.css` (dots + alias bridge) → `base.css` (fonts,
texture, primitives) → `app.css` (components). Use `var(--token)` only; never a
literal hex or radius. Accent is teal `--blue`.
