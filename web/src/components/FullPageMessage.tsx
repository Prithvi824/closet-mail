import type { ReactNode } from "react";

interface FullPageMessageProps {
  title: string;
  body?: ReactNode;
}

/** Centered status message for loading and error states. */
export function FullPageMessage({ title, body }: FullPageMessageProps) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-2 p-6 text-center">
      <h2 className="text-lg font-medium">{title}</h2>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
    </div>
  );
}
