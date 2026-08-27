import { AlertIcon } from "./icons";

export default function ErrorCard({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="flex w-full animate-fade-in-up justify-start" role="alert">
      <div className="flex max-w-[85%] items-start gap-3 rounded-lg border border-outline-variant bg-error-surface p-4">
        <AlertIcon className="mt-0.5 h-5 w-5 shrink-0 text-error" />
        <div className="flex flex-col items-start gap-2">
          <p className="text-body-md text-on-surface">{text}</p>
          <button
            type="button"
            onClick={onRetry}
            className="rounded px-2 py-1 text-label-sm text-primary-accent underline underline-offset-4 hover:bg-surface-container"
          >
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}
