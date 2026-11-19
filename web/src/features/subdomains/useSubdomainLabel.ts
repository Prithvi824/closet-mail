import { useParams } from "react-router";

/** The subdomain label of the current /s/:label/... route. */
export function useSubdomainLabel(): string {
  const { label } = useParams();
  if (!label) throw new Error("useSubdomainLabel must be used inside a /s/:label route");
  return label;
}
