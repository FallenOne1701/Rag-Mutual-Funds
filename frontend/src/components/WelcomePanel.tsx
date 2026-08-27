import { EXAMPLE_QUESTIONS } from "../constants";

interface Props {
  onPick: (question: string) => void;
  disabled: boolean;
}

export default function WelcomePanel({ onPick, disabled }: Props) {
  return (
    <section className="flex flex-col items-center gap-stack-md rounded-lg border border-outline-variant bg-surface px-5 py-8 text-center shadow-float">
      <div className="flex flex-col gap-2">
        <h2 className="text-headline-md text-on-surface">Ask about five HDFC schemes</h2>
        <p className="mx-auto max-w-md text-body-md text-on-surface-variant">
          Every answer is at most three sentences and links back to the official Groww scheme page
          it came from.
        </p>
      </div>

      <ul className="flex w-full flex-col items-stretch gap-2 sm:w-auto sm:items-center">
        {EXAMPLE_QUESTIONS.map((q) => (
          <li key={q} className="w-full">
            <button
              type="button"
              onClick={() => onPick(q)}
              disabled={disabled}
              className="w-full rounded-full border border-outline-variant px-4 py-2.5 text-body-md text-on-surface-variant transition-colors hover:border-primary-accent hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-50"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
