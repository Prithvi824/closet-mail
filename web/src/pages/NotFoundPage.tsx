import { Link } from "react-router";

import { FullPageMessage } from "@/components/FullPageMessage";

export function NotFoundPage() {
  return (
    <FullPageMessage
      title="Page not found"
      body={<Link to="/overview" className="underline underline-offset-4">Go to the overview</Link>}
    />
  );
}
