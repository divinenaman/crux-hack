import React, { useState } from "react";

const RATIOS = ["1:1", "4:5", "9:16", "16:9"];

export default function PromptBar({ onRun, busy }) {
  const [text, setText] = useState("Create 4 different images like this: Get a Xero Coach. Get ahead. — a quirky campaign ad for small business owners");
  const [ratio, setRatio] = useState("1:1");
  const [variants, setVariants] = useState(4);

  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>Use case</div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        style={{ width: "100%", borderRadius: 10, border: "1px solid #dfe5f1", padding: 10, font: "inherit", resize: "vertical" }}
        placeholder="What should the ad do? Who is it for? Tone?"
      />
      <div style={{ display: "flex", gap: 6, margin: "10px 0", alignItems: "center", flexWrap: "wrap" }}>
        {RATIOS.map((r) => (
          <button
            key={r}
            onClick={() => setRatio(r)}
            style={{
              border: "1px solid #dfe5f1",
              background: ratio === r ? "#0b1a3a" : "#fff",
              color: ratio === r ? "#fff" : "#0b1a3a",
              borderRadius: 8,
              padding: "6px 10px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {r}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
          variants
          <select
            value={variants}
            onChange={(e) => setVariants(Number(e.target.value))}
            style={{ borderRadius: 8, border: "1px solid #dfe5f1", padding: "5px 8px", font: "inherit", fontWeight: 600, background: "#fff" }}
          >
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        disabled={busy || !text.trim()}
        onClick={() => onRun(text.trim(), ratio, variants)}
        style={{
          width: "100%",
          padding: "12px 14px",
          borderRadius: 12,
          border: "none",
          background: busy ? "#9db1dd" : "#00a3e0",
          color: "#fff",
          fontWeight: 800,
          fontSize: 15,
          cursor: busy ? "wait" : "pointer",
        }}
      >
        {busy ? "Agent working…" : "Generate with agent"}
      </button>
      <div style={{ fontSize: 11, opacity: 0.6, marginTop: 8 }}>
        ingest → brief → compose → judge loop → fidelity paste → editable canvas
      </div>
    </div>
  );
}
