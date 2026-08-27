/** Mirrors the Architecture response contract served by POST /chat. */

export interface Citation {
  url: string;
  title: string;
}

export interface ChatResponse {
  type: "answer" | "refusal";
  text: string;
  citation: Citation;
  footer: string;
  disclaimer: string;
  meta?: Record<string, unknown> | null;
}

export interface SchemeInfo {
  scheme_id: string;
  scheme_name: string;
  category: string;
  url: string;
}

export interface SchemesResponse {
  count: number;
  schemes: SchemeInfo[];
}

export interface HealthResponse {
  status: "ok" | "degraded";
  phase: string;
  index: { ready: boolean; vectors: number | null; collection: string; detail?: string | null };
  groq: { configured: boolean; model: string };
  disclaimer: string;
}

export type Message =
  | { id: string; role: "user"; text: string }
  | { id: string; role: "assistant"; response: ChatResponse }
  | { id: string; role: "error"; text: string; retry: string };
