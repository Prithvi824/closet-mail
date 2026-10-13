import { CheckIcon, CopyIcon } from "lucide-react";
import { useEffect, useState, type MouseEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";

interface CopyButtonProps {
  value: string;
  /** Accessible label, e.g. "Copy address". */
  label?: string;
}

const RESET_MS = 1500;

/** Icon button that copies a value and briefly shows a check mark. */
export function CopyButton({ value, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  async function copy(event: MouseEvent) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      toast.error("Copy failed; select the text instead");
    }
  }

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), RESET_MS);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <Button type="button" variant="ghost" size="icon-xs" aria-label={label} onClick={copy}>
      {copied ? <CheckIcon /> : <CopyIcon />}
    </Button>
  );
}
