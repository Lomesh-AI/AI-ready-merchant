"use client";
import { useRef, useState } from "react";

const DEMO_USER_TOKEN = "demo-user-token-1";

export default function BuyerPage() {
  const [merchantUrl, setMerchantUrl] = useState("http://localhost:8000");
  const [goal, setGoal] = useState(
    "Buy beginner running shoes under ₹5,000. You may purchase if you find a good option."
  );
  const [events, setEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(null);
  const esRef = useRef(null);

  function push(kind, data) {
    setEvents((e) => [...e, { kind, data, ts: new Date().toLocaleTimeString() }]);
  }

  function openRazorpay(payload) {
    if (typeof window === "undefined" || !window.Razorpay) return;
    new window.Razorpay({
      key: payload.key_id,
      order_id: payload.order_id,
      amount: payload.amount_paise,
      currency: "INR",
      name: "Acme Outdoors",
      description: "Agent purchase (test mode)",
      handler: (resp) =>
        push("status", { text: `Razorpay payment submitted: ${resp.razorpay_payment_id}` }),
    }).open();
  }

  async function approve(url) {
    try {
      const r = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${DEMO_USER_TOKEN}` },
      });
      const j = await r.json();
      push("status", { text: `Approved: ${JSON.stringify(j)}` });
    } catch (e) {
      push("status", { text: `Approval failed: ${e}` });
    }
  }

  async function start() {
    setEvents([]);
    setDone(null);
    setRunning(true);
    const r = await fetch("/buyer-api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ merchant_url: merchantUrl, goal }),
    });
    const { session_id } = await r.json();
    const es = new EventSource(`/buyer-api/session/${session_id}/stream`);
    esRef.current = es;
    const on = (name, fn) => es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
    on("agent_thought", (d) => push("thought", d));
    on("tool_call", (d) => push("tool_call", d));
    on("tool_result", (d) => push("tool_result", d));
    on("gate", (d) => push("gate", d));
    on("status", (d) => push("status", d));
    on("consent_required", (d) => push("consent", d));
    on("user_action", (d) => {
      push("user_action", d);
      if (d.type === "razorpay_checkout") openRazorpay(d.payload);
    });
    on("done", (d) => {
      push("done", d);
      setDone(d.result);
      setRunning(false);
      es.close();
    });
  }

  const kindStyle = {
    thought: "border-l-sky-500",
    tool_call: "border-l-violet-500",
    tool_result: "border-l-zinc-600",
    gate: "border-l-emerald-500",
    status: "border-l-zinc-700",
    consent: "border-l-amber-500",
    user_action: "border-l-pink-500",
    done: "border-l-emerald-400",
  };

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <h1 className="text-2xl font-bold">🤖 AI Buyer Agent</h1>
      <div className="space-y-3 bg-zinc-900 rounded-xl p-5 border border-zinc-800">
        <label className="block text-sm text-zinc-400">Merchant URL</label>
        <input
          className="w-full bg-zinc-800 rounded px-3 py-2 font-mono text-sm"
          value={merchantUrl}
          onChange={(e) => setMerchantUrl(e.target.value)}
        />
        <label className="block text-sm text-zinc-400">Goal</label>
        <textarea
          className="w-full bg-zinc-800 rounded px-3 py-2 text-sm"
          rows={2}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <button
          onClick={start}
          disabled={running}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded px-4 py-2 font-semibold"
        >
          {running ? "Running…" : "Run agent"}
        </button>
        <p className="text-xs text-zinc-500">
          Test cards — SUCCESS: <b>4111 1111 1111 1111</b> · FAILURE:{" "}
          <b>4000 0000 0000 0002</b> (any future expiry, any CVV)
        </p>
      </div>

      <div className="space-y-2">
        {events.map((e, i) => (
          <div key={i} className={`bg-zinc-900 border-l-4 rounded-r px-4 py-2 text-sm ${kindStyle[e.kind]}`}>
            <span className="text-zinc-500 font-mono text-xs mr-2">{e.ts}</span>
            {e.kind === "gate" && (
              <span>
                {e.data.verdict?.includes("REJECT") ? "✗" : "✓"}{" "}
                <b>GATE {e.data.verdict}</b> — {e.data.reason}
              </span>
            )}
            {e.kind === "thought" && <span className="text-sky-300">💭 {e.data.text}</span>}
            {e.kind === "tool_call" && (
              <span className="text-violet-300 font-mono">
                🛠 {e.data.name}({JSON.stringify(e.data.args).slice(0, 300)})
              </span>
            )}
            {e.kind === "tool_result" && (
              <span className="text-zinc-400 font-mono text-xs block whitespace-pre-wrap break-all">
                {e.data.summary}
              </span>
            )}
            {e.kind === "status" && <span className="text-zinc-300">ℹ {e.data.text}</span>}
            {e.kind === "consent" && (
              <div className="text-amber-300">
                <p>
                  🔐 Consent required: <b>{e.data.kind}</b> — scope:{" "}
                  {JSON.stringify(e.data.scope)}
                </p>
                {e.data.approval_url && (
                  <button
                    onClick={() => approve(e.data.approval_url)}
                    className="mt-2 bg-amber-600 hover:bg-amber-500 text-black rounded px-3 py-1 font-semibold text-xs"
                  >
                    Approve
                  </button>
                )}
              </div>
            )}
            {e.kind === "user_action" && (
              <div className="text-pink-300">
                👉 <b>{e.data.type}</b>{" "}
                {e.data.type === "payment_link" ? (
                  <a className="underline" href={e.data.payload?.url} target="_blank">
                    Open payment link
                  </a>
                ) : (
                  <span className="font-mono text-xs">{JSON.stringify(e.data.payload)}</span>
                )}
              </div>
            )}
            {e.kind === "done" && (
              <span className="text-emerald-300 font-semibold">🏁 {e.data.result}</span>
            )}
          </div>
        ))}
      </div>

      {done && (
        <div className="bg-emerald-950 border border-emerald-800 rounded-xl p-4">
          <p className="font-semibold">Session complete</p>
          <p className="text-sm text-zinc-300">{done}</p>
          <a className="text-emerald-400 underline text-sm" href="/merchant" target="_blank">
            View in audit →
          </a>
        </div>
      )}
    </main>
  );
}
