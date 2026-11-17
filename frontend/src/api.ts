import type { Message } from "./types";

const CLIENT_HEADER = { "X-SpeakLab-Client": "1" };
const UNREACHABLE =
  "SpeakLab’s local server could not be reached. Start the backend and try again.";

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      ...options,
      headers: {
        ...CLIENT_HEADER,
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error(UNREACHABLE);
  }
  if (!response.ok) throw await failure(response);
  return response.json() as Promise<T>;
}
/** A refused request, with the HTTP status so callers can treat a 404 or 409 calmly. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}
async function failure(response: Response) {
  const data = await response.json().catch(() => ({}));
  return new ApiError(
    typeof data.detail === "string"
      ? data.detail
      : `The request could not be completed (${response.status}). Check your input and try again.`,
    response.status,
  );
}
/** The chat request was refused or never reached the server, so the question wasn't stored. */
export class ChatNotSent extends Error {}

/** Send a chat message and stream the coach's reply. Resolves with the stored reply. */
export async function streamChat(
  sessionId: string,
  attempt: number,
  message: string,
  onDelta: (text: string) => void,
): Promise<Message> {
  let response: Response;
  try {
    response = await fetch(`/api/sessions/${sessionId}/chat`, {
      method: "POST",
      headers: { ...CLIENT_HEADER, "Content-Type": "application/json" },
      body: JSON.stringify({ message, attempt_number: attempt }),
    });
  } catch {
    throw new ChatNotSent(UNREACHABLE);
  }
  if (!response.ok) throw new ChatNotSent((await failure(response)).message);
  if (!response.body) throw new Error("The coach’s reply could not be read.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handle = (block: string): Message | null => {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return null;
    const event = JSON.parse(data) as {
      delta?: string;
      done?: boolean;
      message?: Message;
      error?: string;
    };
    if (event.error) throw new Error(event.error);
    if (event.done && event.message) return event.message;
    if (event.delta) onDelta(event.delta);
    return null;
  };
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = done ? "" : (blocks.pop() ?? "");
    for (const block of blocks) {
      const result = handle(block);
      if (result) {
        void reader.cancel().catch(() => {});
        return result;
      }
    }
    if (done) break;
  }
  throw new Error(
    "The coach’s reply stopped before it finished. Your question is saved; try again.",
  );
}
export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(body) });
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong. Try again.";
export const dateLabel = (date: string) =>
  new Date(date.length === 10 ? date + "T12:00:00" : date).toLocaleDateString(
    undefined,
    { month: "short", day: "numeric", year: "numeric" },
  );
export const timeLabel = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
