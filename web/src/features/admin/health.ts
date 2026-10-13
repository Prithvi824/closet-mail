import type { TileStatus } from "@/features/admin/HealthTile";
import type { Health } from "@/lib/api";

/** The processor writes its heartbeat every loop (TTL 120 s); 5 minutes without one is down. */
const HEARTBEAT_STALE_SECONDS = 300;
const SEND_WARN_RATIO = 0.8;

export function heartbeatStatus(health: Health): TileStatus {
  const age = health.heartbeat_age_seconds;
  if (age === null || age === undefined) return "bad";
  return age < HEARTBEAT_STALE_SECONDS ? "ok" : "bad";
}

export function backlogStatus(count: number | null | undefined, isDlq: boolean): TileStatus {
  if (count === null || count === undefined) return "unknown";
  if (count === 0) return "ok";
  return isDlq ? "bad" : "warn";
}

export function sendStatus(health: Health): TileStatus {
  if (health.sends_today >= health.send_cap) return "bad";
  return health.sends_today >= health.send_cap * SEND_WARN_RATIO ? "warn" : "ok";
}

/** "42 s", "7 min", "3 h". */
export function formatAge(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}
