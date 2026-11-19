/** API path inside one subdomain's scope (the shared axios instance adds /api/v1). */
export function sub(label: string, path: string): string {
  return `/subdomains/${encodeURIComponent(label)}${path}`;
}

/** Dashboard path of one section of a subdomain, e.g. /s/acme/aliases. */
export function subdomainPage(label: string, section: string): string {
  return `/s/${encodeURIComponent(label)}/${section}`;
}
