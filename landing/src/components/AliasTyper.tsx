/** Types out example alias names one after another, as a hint of what generated aliases look like. */

import { useEffect, useState } from "react";

interface AliasTyperProps {
  aliases: readonly string[];
}

const TYPE_MS = 70;
const DELETE_MS = 35;
const HOLD_MS = 2200;

export function AliasTyper({ aliases }: AliasTyperProps) {
  const [index, setIndex] = useState(0);
  const [length, setLength] = useState(aliases[0]?.length ?? 0);
  const [deleting, setDeleting] = useState(false);

  /** Advance the animation by one keystroke. */
  function step() {
    const word = aliases[index] ?? "";
    if (!deleting && length >= word.length) {
      setDeleting(true);
    } else if (deleting && length <= 0) {
      setDeleting(false);
      setIndex((index + 1) % aliases.length);
    } else {
      setLength(length + (deleting ? -1 : 1));
    }
  }

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const word = aliases[index] ?? "";
    const holding = !deleting && length >= word.length;
    const timer = window.setTimeout(step, holding ? HOLD_MS : deleting ? DELETE_MS : TYPE_MS);
    return () => window.clearTimeout(timer);
  });

  return (
    <span>
      {(aliases[index] ?? "").slice(0, length)}
      <span aria-hidden="true" className="ml-0.5 inline-block h-[1em] w-[7px] animate-blink bg-ice align-[-2px]" />
    </span>
  );
}
