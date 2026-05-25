"use client";

import { useState } from "react";

export default function Home() {
  const [cvText, setCvText] = useState("");
  const [status, setStatus] = useState("idle");

  const startBlitz = async () => {
    setStatus("processing");
    try {
      const res = await fetch("http://localhost:8000/api/v1/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: "user123", cv_text: cvText }),
      });
      const data = await res.json();
      setStatus(`Started Thread: ${data.thread_id}`);
    } catch (err) {
      console.error(err);
      setStatus("Error starting process.");
    }
  };

  return (
    <main className="min-h-screen p-12 max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">AI Recruitment Agent</h1>

      <div className="bg-white p-6 rounded shadow-sm border mb-8">
        <h2 className="text-xl font-semibold mb-4">1. Insert CV Data</h2>
        <textarea
          className="w-full border p-3 rounded h-40 mb-4"
          placeholder="Paste your CV or experience here..."
          value={cvText}
          onChange={(e) => setCvText(e.target.value)}
        />
        <button
          onClick={startBlitz}
          className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 transition"
        >
          Start Application Blitz
        </button>
      </div>

      <div className="bg-white p-6 rounded shadow-sm border">
        <h2 className="text-xl font-semibold mb-4">2. Agent Status</h2>
        <div className="p-4 bg-slate-50 border rounded text-sm text-slate-700 font-mono">
          Current Status: {status}
        </div>
      </div>
    </main>
  );
}