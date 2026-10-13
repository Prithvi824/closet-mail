# Web dashboard

Vite + React 19 + TypeScript SPA for the mail-alias service (see the repository README).

| Command | Purpose |
|---|---|
| `npm ci` | Install |
| `npm run dev` | Dev server on :5173; proxies `/api`, `/hooks`, `/a/`, `/healthz` to the API on :8000 |
| `npm test` | Vitest + Testing Library |
| `npm run lint` | oxlint (generated `src/components/ui` and `src/lib/api-types.ts` are ignored) |
| `npm run build` | Type-check and build to `dist/` |
| `make api-types` (repo root) | Regenerate `src/lib/api-types.ts` from the backend schema |

Layout:
- `src/lib/http.ts` is the one axios instance: cookie session, CSRF header, and a redirect to login on 401.
- `src/lib/api.ts` holds named aliases for the generated API types.
- `src/features/<area>/` has the query/mutation hooks (`api.ts`) and the components for each area.
- `src/pages/` has the route components; `src/app/router.tsx` lazy-loads every signed-in page.
- `src/components/ui/` contains generated shadcn components (radix-nova preset). Add more with `npx shadcn add <name>`.
