import { createContext, useContext } from "react";

export type Theme = "light" | "dark" | "system";

/** localStorage key; index.html reads the same key before first paint to avoid a flash. */
export const THEME_STORAGE_KEY = "mailalias-theme";

export interface ThemeContextValue {
  theme: Theme;
  resolvedTheme: "light" | "dark";
  setTheme: (theme: Theme) => void;
}

export const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("useTheme must be used inside ThemeProvider");
  return value;
}
