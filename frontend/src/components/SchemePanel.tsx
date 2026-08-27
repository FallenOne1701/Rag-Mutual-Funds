import { LinkIcon } from "./icons";
import type { SchemeInfo } from "../types";

export default function SchemePanel({ schemes }: { schemes: SchemeInfo[] }) {
  if (schemes.length === 0) return null;

  return (
    <details className="group rounded-lg border border-outline-variant bg-surface" open>
      <summary className="cursor-pointer list-none px-4 py-3 text-label-sm uppercase tracking-wide text-outline marker:hidden">
        Covered schemes ({schemes.length})
      </summary>
      <ul className="flex flex-col gap-1 border-t border-outline-variant p-2">
        {schemes.map((s) => (
          <li key={s.scheme_id}>
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between gap-2 rounded px-2 py-2 transition-colors hover:bg-surface-container"
            >
              <span className="min-w-0">
                <span className="block truncate text-body-md text-on-surface">{s.scheme_name}</span>
                <span className="text-label-sm text-outline">{s.category}</span>
              </span>
              <LinkIcon className="h-4 w-4 shrink-0 text-primary-accent" />
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}
