import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { AuditEntry, DeadMessage, FingerprintGroup, QueueInfo, ReplayResult } from "./types";

const REASON_CLASS: Record<string, string> = {
  rejected: "chip chip-rejected",
  expired: "chip chip-expired",
  delivery_limit: "chip chip-limit",
  maxlen: "chip chip-limit",
};

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m ago`;
}

function Payload({ raw }: { raw: string }) {
  let pretty = raw;
  try {
    pretty = JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    /* not JSON, show as-is */
  }
  return <pre className="payload">{pretty}</pre>;
}

interface ReplayPanelProps {
  queue: string;
  group: FingerprintGroup | null;
  onDone: (r: ReplayResult) => void;
}

function ReplayPanel({ queue, group, onDone }: ReplayPanelProps) {
  const [max, setMax] = useState(50);
  const [rate, setRate] = useState(25);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<ReplayResult | null>(null);

  const fire = async (dryRun: boolean) => {
    setBusy(true);
    try {
      const r = await api.replay({
        queue,
        fingerprint: group?.fingerprint ?? null,
        max_messages: max,
        rate_per_sec: rate,
        dry_run: dryRun,
      });
      setLast(r);
      onDone(r);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="replay-panel">
      <div className="replay-title">
        Replay {group ? <span className="mono">{group.label}</span> : <em>entire queue</em>}
      </div>
      <div className="replay-controls">
        <label>
          max <input type="number" value={max} min={1} max={1000} onChange={(e) => setMax(+e.target.value)} />
        </label>
        <label>
          msgs/sec <input type="number" value={rate} min={1} max={500} onChange={(e) => setRate(+e.target.value)} />
        </label>
        <button className="btn btn-ghost" disabled={busy} onClick={() => fire(true)}>
          Dry run
        </button>
        <button className="btn btn-fire" disabled={busy} onClick={() => fire(false)}>
          {busy ? "Replaying…" : "Replay"}
        </button>
      </div>
      {last && (
        <div className={"replay-result" + (last.dry_run ? " dry" : "")}>
          {last.dry_run
            ? `dry run: ${last.matched} matched, nothing moved`
            : `${last.replayed} replayed · ${last.returned_to_dlq} bounced back to DLQ · ${last.duration_ms}ms`}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [mode, setMode] = useState("…");
  const [queues, setQueues] = useState<QueueInfo[]>([]);
  const [activeQueue, setActiveQueue] = useState<string | null>(null);
  const [groups, setGroups] = useState<FingerprintGroup[]>([]);
  const [activeGroup, setActiveGroup] = useState<FingerprintGroup | null>(null);
  const [messages, setMessages] = useState<DeadMessage[]>([]);
  const [openMsg, setOpenMsg] = useState<DeadMessage | null>(null);
  const [auditRows, setAuditRows] = useState<AuditEntry[]>([]);
  const [showAudit, setShowAudit] = useState(false);

  const refresh = useCallback(async (queue?: string | null, group?: FingerprintGroup | null) => {
    const qs = await api.queues();
    setQueues(qs);
    const q = queue ?? qs[0]?.name ?? null;
    if (q && !queue) setActiveQueue(q);
    if (q) {
      const gs = await api.groups(q);
      setGroups(gs);
      const g = group ? gs.find((x) => x.fingerprint === group.fingerprint) ?? null : null;
      setActiveGroup(g);
      setMessages(await api.messages(q, g?.fingerprint));
    }
    setAuditRows(await api.audit());
  }, []);

  useEffect(() => {
    api.health().then((h) => setMode(h.mode));
    refresh();
  }, [refresh]);

  const pickQueue = async (name: string) => {
    setActiveQueue(name);
    setActiveGroup(null);
    setOpenMsg(null);
    setGroups(await api.groups(name));
    setMessages(await api.messages(name));
  };

  const pickGroup = async (g: FingerprintGroup) => {
    const next = activeGroup?.fingerprint === g.fingerprint ? null : g;
    setActiveGroup(next);
    setOpenMsg(null);
    if (activeQueue) setMessages(await api.messages(activeQueue, next?.fingerprint));
  };

  const total = queues.reduce((n, q) => n + q.message_count, 0);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="pulse" />
          dlq-pilot
        </div>
        <div className="topbar-right">
          <span className="stat">{total} dead letters</span>
          <span className={"mode-badge " + (mode === "demo" ? "demo" : "live")}>{mode} mode</span>
          <button className="btn btn-ghost" onClick={() => refresh(activeQueue, activeGroup)}>
            Refresh
          </button>
        </div>
      </header>

      <div className="columns">
        <aside className="sidebar">
          <div className="side-head">Dead-letter queues</div>
          {queues.map((q) => (
            <button
              key={q.name}
              className={"queue-row" + (q.name === activeQueue ? " active" : "")}
              onClick={() => pickQueue(q.name)}
            >
              <span className="queue-name mono">{q.name}</span>
              <span className="count">{q.message_count}</span>
            </button>
          ))}
        </aside>

        <main className="main">
          <div className="main-head">
            <h2>Failure groups {activeQueue && <span className="mono dim">· {activeQueue}</span>}</h2>
            <span className="dim">{groups.length} distinct causes</span>
          </div>
          <table className="groups">
            <thead>
              <tr>
                <th>cause</th>
                <th>reason</th>
                <th>origin</th>
                <th className="num">count</th>
                <th>last seen</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr
                  key={g.fingerprint}
                  className={activeGroup?.fingerprint === g.fingerprint ? "active" : ""}
                  onClick={() => pickGroup(g)}
                >
                  <td className="mono label">{g.label || "(no error signature)"}</td>
                  <td>
                    <span className={REASON_CLASS[g.reason] ?? "chip"}>{g.reason}</span>
                  </td>
                  <td className="mono dim">{g.origin_queue}</td>
                  <td className="num strong">{g.count}</td>
                  <td className="dim">{timeAgo(g.last_seen)}</td>
                </tr>
              ))}
              {groups.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    Queue drained — nothing dead here. 🎉
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {activeQueue && (
            <ReplayPanel
              queue={activeQueue}
              group={activeGroup}
              onDone={() => refresh(activeQueue, activeGroup)}
            />
          )}
        </main>

        <aside className="inspector">
          <div className="side-head">
            Messages {activeGroup && <span className="dim">· {activeGroup.count} in group</span>}
          </div>
          <div className="msg-list">
            {messages.slice(0, 50).map((m) => (
              <div key={m.id} className="msg">
                <button className="msg-head" onClick={() => setOpenMsg(openMsg?.id === m.id ? null : m)}>
                  <span className="mono">{m.id.slice(0, 10)}</span>
                  <span className="dim">×{m.death_count}</span>
                  <span className="dim">{timeAgo(m.first_death_at)}</span>
                </button>
                {openMsg?.id === m.id && (
                  <div className="msg-body">
                    <div className="kv">
                      <span>exchange</span>
                      <span className="mono">{m.exchange || "(default)"}</span>
                    </div>
                    <div className="kv">
                      <span>routing key</span>
                      <span className="mono">{m.routing_key}</span>
                    </div>
                    <Payload raw={m.payload} />
                    <pre className="payload headers">{JSON.stringify(m.headers, null, 2)}</pre>
                  </div>
                )}
              </div>
            ))}
            {messages.length === 0 && <div className="empty">no messages</div>}
          </div>
        </aside>
      </div>

      <footer className="auditbar">
        <button className="btn btn-ghost" onClick={() => setShowAudit(!showAudit)}>
          Audit log {showAudit ? "▾" : "▸"} <span className="dim">({auditRows.length})</span>
        </button>
        {showAudit && (
          <div className="audit-rows">
            {auditRows.map((a, i) => (
              <div key={i} className="audit-row mono">
                <span className="dim">{new Date(a.ts).toLocaleTimeString()}</span>
                <span>{a.dry_run ? "dry-run" : "replay"}</span>
                <span>{a.queue}</span>
                <span className="dim">{a.fingerprint ?? "whole queue"}</span>
                <span>
                  {a.replayed}/{a.matched}
                </span>
              </div>
            ))}
          </div>
        )}
      </footer>
    </div>
  );
}
