import { LinkIcon } from "./icons";
import type { Citation } from "../types";

/** Renders the single allowlisted Groww citation returned by the API. */
export default function SourceLink({ citation }: { citation: Citation }) {
  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-center justify-between gap-3 rounded border border-outline-variant bg-surface-container px-3 py-2.5 transition-colors hover:border-primary-accent"
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <LinkIcon className="h-4 w-4 shrink-0 text-primary-accent" />
        <span className="truncate text-body-md text-on-surface-variant underline decoration-outline-variant underline-offset-4 group-hover:decoration-primary-accent">
          {citation.title}
        </span>
      </span>
      <span className="shrink-0 text-label-sm text-outline">Groww</span>
    </a>
  );
}
