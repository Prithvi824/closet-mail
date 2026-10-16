/** Same rule as the backend: starts with a letter/digit, then letters, digits, . _ - (max 64). */
const LOCAL_PART_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;

/** Error message for a custom local part, or null when it is acceptable. */
export function localPartError(value: string): string | null {
  const local = value.trim().toLowerCase();
  if (!local) return "Enter the part before the @";
  if (!LOCAL_PART_RE.test(local) || local.includes("..")) {
    return "Use letters, digits, dots, hyphens or underscores (start with a letter or digit)";
  }
  if (local.endsWith(".")) return "The address can't end with a dot";
  return null;
}
