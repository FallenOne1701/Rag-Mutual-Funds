import SourceLink from "./SourceLink";
import { ShieldIcon, SparkIcon } from "./icons";
import type { ChatResponse } from "../types";

const INTENT_LABELS: Record<string, string> = {
  advisory: "Investment advice — not answered",
  comparative: "Fund comparison — not answered",
  performance: "Returns — not calculated",
  performance_calc: "Returns — not calculated",
  pii: "Personal data — not accepted",
  personal: "Personal data — not accepted",
  account: "Personal data — not accepted",
  out_of_scope: "Out of scope",
};

function refusalLabel(meta: ChatResponse["meta"]): string {
  const intent = typeof meta?.intent === "string" ? meta.intent : "";
  return INTENT_LABELS[intent] ?? "Outside the facts-only scope";
}

export default function AssistantCard({ response }: { response: ChatResponse }) {
  const isRefusal = response.type === "refusal";

  return (
    <div className="flex w-full animate-fade-in-up justify-start">
      <div className="flex w-full max-w-[92%] gap-3 sm:max-w-[85%]">
        <div
          className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
            isRefusal ? "bg-secondary text-on-secondary" : "bg-primary text-on-primary"
          }`}
          aria-hidden
        >
          {isRefusal ? <ShieldIcon className="h-4 w-4" /> : <SparkIcon className="h-4 w-4" />}
        </div>

        <div
          className={`flex min-w-0 flex-col gap-stack-md rounded-lg rounded-tl-sm border p-5 shadow-float ${
            isRefusal
              ? "border-outline-variant bg-surface-container"
              : "border-outline-variant bg-surface"
          }`}
        >
          {isRefusal && (
            <span className="flex items-center gap-2 text-label-sm uppercase tracking-wide text-on-secondary-container">
              <ShieldIcon className="h-4 w-4" />
              {refusalLabel(response.meta)}
            </span>
          )}

          <p className="whitespace-pre-line text-body-lg text-on-surface">{response.text}</p>

          <SourceLink citation={response.citation} />

          <div className="flex flex-col gap-1 border-t border-outline-variant pt-3">
            <p className="text-label-sm text-outline">{response.footer}</p>
            <p className="text-[11px] leading-4 text-outline">{response.disclaimer}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
