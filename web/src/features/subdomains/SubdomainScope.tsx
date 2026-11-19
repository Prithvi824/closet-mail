import { Outlet, useParams } from "react-router";

/**
 * Route element for /s/:label. Keying the outlet by label remounts the page when the operator
 * switches subdomain, so no state or cached view of the previous subdomain carries over.
 */
export function SubdomainScope() {
  const { label } = useParams();
  return <Outlet key={label} />;
}
