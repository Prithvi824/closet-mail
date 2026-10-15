/** Joins class names, skipping falsy values. */

/**
 * Combine class names into one string.
 *
 * Args:
 *   classes: Class names; false, null and undefined are dropped.
 * Returns:
 *   The space-separated class string.
 */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
