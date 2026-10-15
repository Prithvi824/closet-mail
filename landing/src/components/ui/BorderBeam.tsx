/** Magic UI Border Beam: a short light that travels around its parent's border. */

import { motion, type MotionStyle } from "motion/react";
import type { CSSProperties } from "react";

import { cn } from "@/lib/cn";

interface BorderBeamProps {
  /** Length of the beam in px. */
  size?: number;
  /** Seconds for one lap. */
  duration?: number;
  /** Seconds into the lap to start at, so several beams can be staggered. */
  delay?: number;
  colorFrom?: string;
  colorTo?: string;
  borderWidth?: number;
  className?: string;
}

export function BorderBeam({
  size = 80,
  duration = 8,
  delay = 0,
  colorFrom = "#a9d4ff",
  colorTo = "rgba(169, 212, 255, 0)",
  borderWidth = 1,
  className,
}: BorderBeamProps) {
  const maskStyle = { "--border-beam-width": `${borderWidth}px` } as CSSProperties;
  const beamStyle = {
    width: size,
    offsetPath: `rect(0 auto auto 0 round ${size}px)`,
    "--color-from": colorFrom,
    "--color-to": colorTo,
  } as MotionStyle;

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 rounded-[inherit] border-(length:--border-beam-width) border-transparent mask-[linear-gradient(transparent,transparent),linear-gradient(#000,#000)] mask-intersect [mask-clip:padding-box,border-box]"
      style={maskStyle}
    >
      <motion.div
        className={cn(
          "absolute aspect-square bg-linear-to-l from-(--color-from) via-(--color-to) to-transparent",
          className,
        )}
        style={beamStyle}
        initial={{ offsetDistance: "0%" }}
        animate={{ offsetDistance: ["0%", "100%"] }}
        transition={{ repeat: Infinity, ease: "linear", duration, delay: -delay }}
      />
    </div>
  );
}
