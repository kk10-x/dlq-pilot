export interface QueueInfo {
  name: string;
  message_count: number;
  origin_queue: string | null;
}

export interface FingerprintGroup {
  fingerprint: string;
  label: string;
  reason: string;
  origin_queue: string;
  count: number;
  sample_payload: string;
  first_seen: string | null;
  last_seen: string | null;
}

export interface DeadMessage {
  id: string;
  queue: string;
  payload: string;
  headers: Record<string, unknown>;
  exchange: string;
  routing_key: string;
  reason: string;
  origin_queue: string;
  death_count: number;
  first_death_at: string | null;
  fingerprint: string;
  fingerprint_label: string;
}

export interface ReplayResult {
  queue: string;
  fingerprint: string | null;
  matched: number;
  replayed: number;
  returned_to_dlq: number;
  dry_run: boolean;
  duration_ms: number;
}

export interface AuditEntry {
  ts: string;
  action: string;
  queue: string;
  fingerprint: string | null;
  matched: number;
  replayed: number;
  dry_run: boolean;
}
