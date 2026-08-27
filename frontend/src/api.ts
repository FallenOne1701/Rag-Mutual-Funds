import type { ChatResponse, HealthResponse, SchemesResponse } from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/$/, "");

/** Chat API refused or failed in a way the UI should surface verbatim. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("Can't reach the assistant service. Is the chat API running?", 0);
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export function sendMessage(message: string, signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ message }),
    signal,
  });
}

export function fetchSchemes(): Promise<SchemesResponse> {
  return request<SchemesResponse>("/schemes");
}

export function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}
