/** Framework-independent browser client. Serve the frontend and API at one origin. */
export type DemoUser = "user1" | "user2";
export type Session = {
  session_key: string;
  title: string;
  updated_at: number | null;
  has_active_run: boolean;
};
export type Activity = {
  id: string; kind: string; phase: string; label: string; terminal: boolean;
  run_id?: string; item_id?: string; sequence?: number; timestamp?: number;
  detail?: string; outcome?: string; approval_id?: string; output_tokens?: number;
  changes?: { added?: number; removed?: number };
  steps?: { text: string; status: "pending" | "in_progress" | "completed" }[];
};
export type InFlight = { run_id: string; text: string; activities: Activity[]; started_at?: number | null };
export type Message = { role: "user" | "assistant" | "activity"; text: string; activities: Activity[] };
export type ChatEvent = {
  session_key: string;
  run_id?: string;
  sequence?: number;
  state?: string;
  delta_text?: string;
  replace?: boolean;
  phase?: string;
  yielded?: boolean;
  activity?: Activity;
  message?: Message;
  error?: { code: string; message: string };
};
export class APIError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    const { csrf_token } = await request<{ csrf_token: string }>("/auth/csrf");
    headers["Content-Type"] = "application/json";
    headers["X-CSRF-Token"] = csrf_token;
  }
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new APIError(response.status, result.error?.code ?? "REQUEST_FAILED",
      result.error?.message ?? "Request failed.");
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export const assistant = {
  login: (user: DemoUser) => request("/auth/login", { user }),
  switchUser: (user: DemoUser) => request("/auth/switch", { user }),
  logout: () => request<void>("/auth/logout", {}),
  me: () => request<{ user: { id: DemoUser; display_name: string } }>("/auth/me"),
  createInstance: () => request<{ instance: { id: string; status: string } }>("/api/instance", {}),
  instance: () => request<{ instance: { id: string; status: string } }>("/api/instance"),
  sessions: (limit = 50, offset = 0) => request<{ sessions: Session[] }>(
    `/api/assistant/sessions?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  createSession: (idempotencyKey: string, title?: string) => request<{ session_key: string }>(
    "/api/assistant/sessions", { idempotency_key: idempotencyKey, ...(title ? { title } : {}) }),
  history: (sessionKey: string, cursor?: string) => request<{
    session_key: string; messages: Message[]; next_cursor: string | null; in_flight: InFlight | null;
  }>(`/api/assistant/history?${new URLSearchParams({ session_key: sessionKey, ...(cursor ? { cursor } : {}) })}`),
  send: (sessionKey: string, message: string, idempotencyKey: string) => request<{
    session_key: string; run_id: string; status: "accepted";
  }>("/api/assistant/messages", { session_key: sessionKey, message, idempotency_key: idempotencyKey }),
  abort: (sessionKey: string, runId: string) => request<{ aborted: boolean }>(
    "/api/assistant/runs/abort", { session_key: sessionKey, run_id: runId }),
  subscribe: (sessionKey: string, handlers: {
    includeApprovals?: boolean;
    onApproval?: (event: { session_key: string; approval: Approval }) => void;
    onApprovalReplay?: (event: { approvals: Approval[] }) => void;
    onReady: () => void;
    onChat: (event: ChatEvent) => void;
    onMessage?: (event: ChatEvent) => void;
    onActivity?: (event: Activity & {session_key: string}) => void;
    onSessionEnded: () => void;
    onReconnectRequired: () => void;
  }): (() => void) => {
    const source = new EventSource(`/api/assistant/events?${new URLSearchParams({ session_key: sessionKey, include_approvals: String(handlers.includeApprovals ?? false) })}`);
    // On every ready (including reconnect), reload history before allowing another send.
    source.addEventListener("ready", () => handlers.onReady());
    source.addEventListener("chat", event => handlers.onChat(JSON.parse((event as MessageEvent).data)));
    source.addEventListener("activity", event => handlers.onActivity?.(JSON.parse((event as MessageEvent).data)));
    source.addEventListener("session.message", event => handlers.onMessage?.(JSON.parse((event as MessageEvent).data)));
    source.addEventListener("session.approval", event => handlers.onApproval?.(JSON.parse((event as MessageEvent).data)));
    source.addEventListener("approval.replay", event => handlers.onApprovalReplay?.(JSON.parse((event as MessageEvent).data)));
    source.addEventListener("error", event => {
      source.close();
      if (event instanceof MessageEvent && JSON.parse(event.data).code === "SESSION_ENDED") {
        handlers.onSessionEnded();
      } else {
        handlers.onReconnectRequired();
      }
    });
    return () => source.close();
  },
};

export type Task = {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "timed_out";
  title: string;
  session_key: string | null;
  run_id: string | null;
  progress: string | null;
  result: string | null;
  error: string | null;
};
export type Approval = {
  id: string;
  status: "pending" | "allowed" | "denied" | "expired" | "cancelled";
  presentation: Record<string, unknown> & {
    kind: "exec" | "plugin" | "system-agent";
    allowedDecisions: string[];
  };
  createdAtMs: number;
  expiresAtMs: number;
  resolvedAtMs?: number;
  decision?: string;
};
export const product = {
  capabilities: () => request<{
    api_version: string;
    instance_status: string;
    features: Record<string, { state: string; description?: string; requires_ready_instance?: boolean }>;
  }>("/api/assistant/capabilities"),
  tasks: (options: { status?: Task["status"]; session_key?: string; cursor?: string } = {}) => request<{
    tasks: Task[]; next_cursor: string | null;
  }>(`/api/assistant/tasks?${new URLSearchParams(options)}`),
  task: (id: string) => request<{ task: Task }>(`/api/assistant/tasks/${encodeURIComponent(id)}`),
  cancelTask: (id: string, reason?: string) => request<{ found: boolean; cancelled: boolean }>(
    `/api/assistant/tasks/${encodeURIComponent(id)}/cancel`, reason ? { reason } : {}),
  pendingApprovals: (sessionKey: string) => request<{ approvals: Approval[]; next_cursor: string | null }>(
    `/api/assistant/approvals?${new URLSearchParams({ session_key: sessionKey })}`),
  approvalHistory: (cursor?: string) => request<{ approvals: Approval[]; next_cursor: string | null }>(
    `/api/assistant/approvals/history?${new URLSearchParams(cursor ? { cursor } : {})}`),
  approval: (id: string) => request<{ approval: Approval; review_token: string | null }>(
    `/api/assistant/approvals/${encodeURIComponent(id)}`),
  resolve: (id: string, decision: "allow-once" | "deny", reviewToken: string) => request<{
    applied: boolean; approval: Approval;
  }>(`/api/assistant/approvals/${encodeURIComponent(id)}/resolve`, { decision, review_token: reviewToken }),
};
