import { useEffect, useRef } from "react";
import { MAX_MESSAGE_CHARS, PRIVACY_NOTE } from "../constants";
import { SendIcon } from "./icons";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  busy: boolean;
}

export default function Composer({ value, onChange, onSend, busy }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  const tooLong = value.length > MAX_MESSAGE_CHARS;
  const canSend = value.trim().length > 0 && !busy && !tooLong;

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <div className="sticky bottom-0 bg-gradient-to-t from-background via-background to-transparent px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-6 sm:px-gutter">
      <div className="mx-auto w-full max-w-conversation">
        <div className="flex items-end rounded-md border border-outline-variant bg-surface p-2 shadow-composer transition-colors focus-within:border-primary-accent">
          <label htmlFor="composer" className="sr-only">
            Ask a factual question about a covered HDFC scheme
          </label>
          <textarea
            id="composer"
            ref={ref}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a factual question about a covered HDFC scheme…"
            className="max-h-40 w-full resize-none border-none bg-transparent px-3 py-2.5 text-body-md text-on-surface placeholder:text-outline focus:outline-none focus:ring-0"
          />
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-label="Send question"
            className="ml-2 flex h-11 w-11 shrink-0 items-center justify-center rounded bg-primary text-on-primary transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <SendIcon />
          </button>
        </div>

        <div className="mt-2 flex items-start justify-between gap-3">
          <p className="text-[11px] leading-4 text-outline">{PRIVACY_NOTE}</p>
          {value.length > MAX_MESSAGE_CHARS * 0.8 && (
            <span className={`text-[11px] ${tooLong ? "text-error" : "text-outline"}`}>
              {value.length}/{MAX_MESSAGE_CHARS}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
