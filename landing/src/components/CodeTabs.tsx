/** Tabbed code sample for the API section. */

import { useState } from "react";

import type { CodeSample, Tone } from "@/lib/apiExamples";
import { cn } from "@/lib/cn";

const TONE_CLASS: Record<Tone, string> = {
  plain: "",
  dim: "text-dim",
  key: "text-ice",
  string: "text-ok",
  field: "text-warn",
};

interface CodeTabsProps {
  tabs: readonly CodeSample[];
}

export function CodeTabs({ tabs }: CodeTabsProps) {
  const [active, setActive] = useState(tabs[0]?.id);

  return (
    <div className="min-w-0 overflow-hidden rounded-2xl border border-line-strong bg-surface">
      <div className="flex gap-0.5 border-b border-line p-2" role="tablist" aria-label="Example language">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`tab-${tab.id}`}
            role="tab"
            type="button"
            aria-selected={tab.id === active}
            aria-controls={`panel-${tab.id}`}
            onClick={() => setActive(tab.id)}
            className={cn(
              "cursor-pointer rounded-lg px-2.5 py-1.5 font-mono text-xs font-medium text-muted",
              tab.id === active && "bg-surface-2 text-fg",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) => (
        <pre
          key={tab.id}
          id={`panel-${tab.id}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab.id}`}
          hidden={tab.id !== active}
          className="m-0 overflow-x-auto px-5 py-4.5 font-mono text-[12.5px] leading-[1.75]"
        >
          {tab.segments.map(([tone, text], position) => (
            <span key={position} className={TONE_CLASS[tone]}>
              {text}
            </span>
          ))}
        </pre>
      ))}
    </div>
  );
}
