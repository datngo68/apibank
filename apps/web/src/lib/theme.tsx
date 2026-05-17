import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Theme = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  resolved: ResolvedTheme;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "apibank.theme";

function readSavedTheme(): Theme {
  if (typeof window === "undefined") return "system";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark" || saved === "system") return saved;
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readSavedTheme());
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    readSavedTheme() === "system" ? (systemPrefersDark() ? "dark" : "light") : (readSavedTheme() as ResolvedTheme),
  );

  useEffect(() => {
    const root = document.documentElement;
    const apply = (next: ResolvedTheme) => {
      root.classList.remove("light", "dark");
      root.classList.add(next);
      root.style.colorScheme = next;
      setResolved(next);
    };

    if (theme === "system") {
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      apply(media.matches ? "dark" : "light");
      const onChange = (e: MediaQueryListEvent) => apply(e.matches ? "dark" : "light");
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    }

    apply(theme);
    return undefined;
  }, [theme]);

  const setTheme = (next: Theme) => {
    window.localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  };

  const value = useMemo<ThemeContextValue>(() => ({ theme, resolved, setTheme }), [theme, resolved]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
