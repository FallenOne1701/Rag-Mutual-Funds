import { DISCLAIMER } from "../constants";
import { MoonIcon, SunIcon } from "./icons";

interface Props {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onReset: () => void;
  canReset: boolean;
}

export default function Header({ theme, onToggleTheme, onReset, canReset }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b border-outline-variant bg-background">
      <div className="mx-auto flex w-full max-w-container items-center justify-between gap-3 px-4 py-3 sm:px-gutter">
        <h1 className="truncate text-headline-md text-on-surface">Mutual Fund FAQ Assistant</h1>

        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden rounded-full border border-outline-variant bg-primary-container px-3 py-1 text-label-sm text-on-primary-container md:inline">
            {DISCLAIMER}
          </span>
          {canReset && (
            <button
              type="button"
              onClick={onReset}
              className="rounded border border-outline-variant px-3 py-1.5 text-label-sm text-on-surface-variant transition-colors hover:bg-surface-container"
            >
              New chat
            </button>
          )}
          <button
            type="button"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="flex h-9 w-9 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container"
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </div>
    </header>
  );
}
