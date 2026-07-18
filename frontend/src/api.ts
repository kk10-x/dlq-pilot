import type { AuditEntry, DeadMessage, FingerprintGroup, QueueInfo, ReplayResult } from "./types";

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export const api = {
  health: () => get<{ status: string; mode: string }>("/api/health"),
  queues: () => get<QueueInfo[]>("/api/queues"),
  groups: (queue: string) => get<FingerprintGroup[]>(`/api/queues/${encodeURIComponent(queue)}/groups`),
  messages: (queue: string, fingerprint?: string) =>
    get<DeadMessage[]>(
      `/api/queues/${encodeURIComponent(queue)}/messages` +
        (fingerprint ? `?fingerprint=${encodeURIComponent(fingerprint)}` : ""),
    ),
  audit: () => get<AuditEntry[]>("/api/audit"),
  replay: async (body: {
    queue: string;
    fingerprint?: string | null;
    max_messages: number;
    rate_per_sec: number;
    dry_run: boolean;
  }): Promise<ReplayResult> => {
    const r = await fetch("/api/replay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`replay failed: ${r.status}`);
    return r.json();
  },
};
