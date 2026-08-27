import { SparkIcon } from "./icons";

export default function PendingCard() {
  return (
    <div className="flex w-full animate-fade-in-up justify-start" aria-live="polite">
      <div className="flex gap-3">
        <div
          className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary"
          aria-hidden
        >
          <SparkIcon className="h-4 w-4" />
        </div>
        <div className="flex items-center gap-3 rounded-lg rounded-tl-sm border border-outline-variant bg-surface px-5 py-4 shadow-float">
          <span className="flex gap-1" aria-hidden>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1.5 w-1.5 animate-blink rounded-full bg-primary-accent"
                style={{ animationDelay: `${i * 160}ms` }}
              />
            ))}
          </span>
          <span className="text-label-sm text-outline">Checking sources…</span>
        </div>
      </div>
    </div>
  );
}
