"use client";
import { useEffect, useState } from "react";

const TOKEN = "demo-user-token-1";
const H = { Authorization: `Bearer ${TOKEN}` };

export default function MerchantPage() {
  const [tab, setTab] = useState("store");
  return (
    <main className="mx-auto max-w-5xl p-8">
      <h1 className="text-2xl font-bold mb-4">🏪 Acme Outdoors — Merchant Control Plane</h1>
      <div className="flex gap-2 mb-6">
        {["store", "audit", "policies", "growth"].map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded px-4 py-2 text-sm font-semibold capitalize ${
              tab === t ? "bg-emerald-600" : "bg-zinc-800 hover:bg-zinc-700"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {tab === "store" && <StoreTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "policies" && <PoliciesTab />}
      {tab === "growth" && <GrowthTab />}
    </main>
  );
}

function StoreTab() {
  const [manifest, setManifest] = useState(null);
  const [healthy, setHealthy] = useState(null);
  useEffect(() => {
    fetch("/merchant-api/agents.json").then((r) => r.json()).then(setManifest);
    fetch("/merchant-api/healthz").then((r) => setHealthy(r.ok));
  }, []);
  return (
    <div className="space-y-4">
      <div className={`rounded-xl p-5 border ${healthy ? "bg-emerald-950 border-emerald-700" : "bg-zinc-900 border-zinc-700"}`}>
        <p className="font-semibold">
          {healthy ? "✅ AI-ready" : "…"} — machine-readable manifest at{" "}
          <code>/.well-known/agents.json</code>
        </p>
        <p className="text-sm text-zinc-400">
          {manifest?.capabilities?.length || 0} capabilities · payment:{" "}
          {manifest?.payment?.provider} ({manifest?.payment?.mode})
        </p>
      </div>
      <pre className="bg-zinc-900 rounded-xl p-5 text-xs overflow-auto border border-zinc-800">
        {JSON.stringify(manifest, null, 2)}
      </pre>
    </div>
  );
}

function AuditTab() {
  const [entries, setEntries] = useState([]);
  const [verify, setVerify] = useState(null);
  const [detail, setDetail] = useState(null);
  const load = () => {
    fetch("/merchant-api/v1/audit/actions", { headers: H })
      .then((r) => r.json()).then(setEntries);
    fetch("/merchant-api/v1/audit/verify", { headers: H })
      .then((r) => r.json()).then(setVerify);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="space-y-4">
      <div className={`inline-block rounded-full px-3 py-1 text-sm font-semibold border ${
        verify?.valid ? "bg-emerald-950 border-emerald-700 text-emerald-300" : "bg-red-950 border-red-700 text-red-300"}`}>
        {verify?.valid ? "🔗 Hash chain valid" : `⛓ Chain broken at seq ${verify?.broken_at_seq}`}
      </div>
      <table className="w-full text-sm bg-zinc-900 rounded-xl overflow-hidden">
        <thead className="bg-zinc-800 text-zinc-400">
          <tr>
            {["seq", "ts", "actor", "action", "decision", "reason", ""].map((h) => (
              <th key={h} className="px-3 py-2 text-left">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.seq} className="border-t border-zinc-800">
              <td className="px-3 py-2 font-mono">{e.seq}</td>
              <td className="px-3 py-2 text-xs text-zinc-500">{String(e.ts).slice(11, 19)}</td>
              <td className="px-3 py-2">{e.actor}</td>
              <td className="px-3 py-2 font-mono text-xs">{e.action_type}</td>
              <td className={`px-3 py-2 font-semibold ${
                e.decision === "REJECT" ? "text-red-400" : e.decision === "ALLOW" ? "text-emerald-400" : "text-zinc-500"}`}>
                {e.decision || "—"}
              </td>
              <td className="px-3 py-2 text-xs">{e.reason || ""}</td>
              <td className="px-3 py-2">
                <button
                  className="text-sky-400 underline text-xs"
                  onClick={() =>
                    fetch(`/merchant-api/v1/audit/actions/${e.seq}`, { headers: H })
                      .then((r) => r.json()).then(setDetail)}
                >
                  Why?
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {detail && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-8"
             onClick={() => setDetail(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-2xl w-full max-h-[80vh] overflow-auto p-6"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-bold">Decision record — seq {detail.seq}</h2>
              <button onClick={() => setDetail(null)} className="text-zinc-400">✕</button>
            </div>
            <pre className="text-xs whitespace-pre-wrap">
              {JSON.stringify(detail.decision_record || detail, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function PoliciesTab() {
  const [rules, setRules] = useState([]);
  const load = () =>
    fetch("/merchant-api/v1/policies", { headers: H }).then((r) => r.json()).then(setRules);
  useEffect(() => { load(); }, []);
  async function save(rule) {
    await fetch("/merchant-api/v1/policies", {
      method: "PUT",
      headers: { ...H, "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    load();
  }
  return (
    <div className="space-y-3">
      {rules.map((r, i) => (
        <div key={r.id} className="bg-zinc-900 rounded-xl p-4 border border-zinc-800 flex items-center gap-3">
          <div className="flex-1">
            <p className="font-mono text-sm">{r.name} <span className="text-zinc-500">({r.rule_type})</span></p>
            <input
              className="w-full mt-1 bg-zinc-800 rounded px-2 py-1 font-mono text-xs"
              defaultValue={JSON.stringify(r.value_json)}
              onBlur={(e) => {
                try { rules[i].value_json = JSON.parse(e.target.value); setRules([...rules]); } catch {}
              }}
            />
          </div>
          <button
            onClick={() => { rules[i].enabled = !rules[i].enabled; setRules([...rules]); save(rules[i]); }}
            className={`rounded px-3 py-1 text-xs font-semibold ${r.enabled ? "bg-emerald-700" : "bg-zinc-700"}`}
          >
            {r.enabled ? "enabled" : "disabled"}
          </button>
          <button onClick={() => save(rules[i])} className="bg-sky-700 rounded px-3 py-1 text-xs font-semibold">
            Save
          </button>
        </div>
      ))}
    </div>
  );
}

function GrowthTab() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    fetch("/merchant-api/v1/stats/aov", { headers: H }).then((r) => r.json()).then(setStats);
  }, []);
  const ai = stats?.ai_assisted_aov_paise || 0;
  const base = stats?.baseline_aov_paise || 0;
  const delta = base ? Math.round(((ai - base) / base) * 100) : 0;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-zinc-900 rounded-xl p-6 border border-zinc-800">
          <p className="text-sm text-zinc-400">AI-assisted AOV</p>
          <p className="text-3xl font-bold text-emerald-400">₹{(ai / 100).toLocaleString()}</p>
          <p className="text-xs text-amber-500 mt-1">simulated data</p>
        </div>
        <div className="bg-zinc-900 rounded-xl p-6 border border-zinc-800">
          <p className="text-sm text-zinc-400">Baseline AOV</p>
          <p className="text-3xl font-bold">₹{(base / 100).toLocaleString()}</p>
          <p className="text-xs text-amber-500 mt-1">simulated data</p>
        </div>
      </div>
      <div className="bg-zinc-900 rounded-xl p-4 border border-zinc-800 text-sm">
        AI-assisted delta: <b className={delta >= 0 ? "text-emerald-400" : "text-red-400"}>
          {delta >= 0 ? "+" : ""}{delta}%
        </b>{" "}
        <span className="text-amber-500">(simulated)</span>
      </div>
    </div>
  );
}
