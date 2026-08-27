import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchSchemes, sendMessage } from "./api";
import AssistantCard from "./components/AssistantCard";
import Composer from "./components/Composer";
import DisclaimerStrip from "./components/DisclaimerStrip";
import ErrorCard from "./components/ErrorCard";
import Header from "./components/Header";
import PendingCard from "./components/PendingCard";
import SchemePanel from "./components/SchemePanel";
import UserBubble from "./components/UserBubble";
import WelcomePanel from "./components/WelcomePanel";
import type { Message, SchemeInfo } from "./types";
import { useTheme } from "./useTheme";

let seq = 0;
const nextId = () => `m${++seq}`;

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [schemes, setSchemes] = useState<SchemeInfo[]>([]);
  const { theme, toggle } = useTheme();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchSchemes()
      .then((data) => setSchemes(data.schemes))
      .catch(() => setSchemes([]));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  const ask = useCallback(
    async (question: string) => {
      const text = question.trim();
      if (!text || busy) return;

      setMessages((prev) => [...prev, { id: nextId(), role: "user", text }]);
      setDraft("");
      setBusy(true);

      try {
        const response = await sendMessage(text);
        setMessages((prev) => [...prev, { id: nextId(), role: "assistant", response }]);
      } catch (err) {
        const detail =
          err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
        setMessages((prev) => [...prev, { id: nextId(), role: "error", text: detail, retry: text }]);
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-full flex-col bg-background">
      <Header
        theme={theme}
        onToggleTheme={toggle}
        onReset={() => setMessages([])}
        canReset={!isEmpty}
      />

      <main className="flex min-h-0 flex-1 flex-col">
        <div className="mx-auto w-full max-w-conversation px-4 pt-stack-md sm:px-gutter">
          <DisclaimerStrip />
        </div>

        <div className="scrollbar-slim flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-conversation flex-col gap-stack-lg px-4 py-stack-md sm:px-gutter">
            {isEmpty && (
              <>
                <WelcomePanel onPick={ask} disabled={busy} />
                <SchemePanel schemes={schemes} />
              </>
            )}

            {messages.map((m) => {
              if (m.role === "user") return <UserBubble key={m.id} text={m.text} />;
              if (m.role === "assistant")
                return <AssistantCard key={m.id} response={m.response} />;
              return <ErrorCard key={m.id} text={m.text} onRetry={() => ask(m.retry)} />;
            })}

            {busy && <PendingCard />}
            <div ref={endRef} />
          </div>
        </div>

        <Composer value={draft} onChange={setDraft} onSend={() => ask(draft)} busy={busy} />
      </main>
    </div>
  );
}
