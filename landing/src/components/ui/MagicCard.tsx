/** Magic UI Magic Card: a border and soft glow that follow the pointer (dark theme only). */

import { motion, useMotionTemplate, useMotionValue } from "motion/react";
import type { PointerEvent, ReactNode } from "react";

import { cn } from "@/lib/cn";

interface MagicCardProps {
  children?: ReactNode;
  className?: string;
  /** Radius of the spotlight in px. */
  gradientSize?: number;
}

export function MagicCard({ children, className, gradientSize = 260 }: MagicCardProps) {
  const mouseX = useMotionValue(-gradientSize);
  const mouseY = useMotionValue(-gradientSize);

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    mouseX.set(event.clientX - rect.left);
    mouseY.set(event.clientY - rect.top);
  }

  function handlePointerLeave() {
    mouseX.set(-gradientSize);
    mouseY.set(-gradientSize);
  }

  const border = useMotionTemplate`
    linear-gradient(var(--color-surface) 0 0) padding-box,
    radial-gradient(${gradientSize}px circle at ${mouseX}px ${mouseY}px,
      rgba(169, 212, 255, 0.55), var(--color-line) 100%) border-box`;
  const glow = useMotionTemplate`
    radial-gradient(${gradientSize * 1.6}px circle at ${mouseX}px ${mouseY}px,
      rgba(169, 212, 255, 0.07), transparent 70%)`;

  return (
    <motion.div
      className={cn("group relative isolate overflow-hidden border border-transparent", className)}
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      style={{ background: border }}
    >
      <motion.div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-0 transition-opacity duration-300 group-hover:opacity-100"
        style={{ background: glow }}
      />
      <div className="relative flex h-full flex-col gap-2.5">{children}</div>
    </motion.div>
  );
}
