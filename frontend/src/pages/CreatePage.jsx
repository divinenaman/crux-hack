import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";

const RATIOS = ["1:1", "4:5", "9:16", "16:9"];

function flatten(nodes, depth = 0, out = []) {
  for (const n of nodes || []) {
    out.push({ path: n.path, label: `${"— ".repeat(depth)}${n.name} (${n.count})` });
    flatten(n.children, depth + 1, out);
  }
  return out;
}

export default function CreatePage() {
  const { brandId } = useParams();
  const nav = useNavigate();
  const [folders, setFolders] = useState([]);
  const [folder, setFolder] = useState("");
  const [text, setText] = useState("Get a Xero Coach. Get ahead. — quirky coaching ad for small business owners");
  const [ratio, setRatio] = useState("1:1");
  const [variants, setVariants] = useState(3);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.tree(brandId).then((t) => setFolders(flatten(t))).catch(() => setFolders([]));
  }, [brandId]);

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const j = await api.createJob(brandId, text.trim(), ratio, variants, folder);
      nav(`/b/${brandId}/j/${j.id}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 28, maxWidth: 720, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0 }}>Create image</h2>
      <div style={{ fontWeight: 700, margin: "10px 0 6px" }}>Asset folder</div>
      <select value={folder} onChange={(e) => setFolder(e.target.value)} style={{ width: "100%", padding: "10px 12px", borderRadius: 10, border: "1px solid #dfe5f1", font: "inherit", background: "#fff" }}>
        <option value="">All asset classes</option>
        {folders.map((f) => (
          <option key={f.path} value={f.path}>{f.label}</option>
        ))}
      </select>

      <div style={{ fontWeight: 700, margin: "14px 0 6px" }}>Use case</div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        style={{ width: "100%", borderRadius: 10, border: "1px solid #dfe5f1", padding: 10, font: "inherit", resize: "vertical" }}
        placeholder="What should the ad do? Who is it for? Tone?"
      />

      <div style={{ display: "flex", gap: 8, margin: "14px 0", alignItems: "center", flexWrap: "wrap" }}>
        {RATIOS.map((r) => (
          <button key={r} onClick={() => setRatio(r)} style={{ border: "1px solid #dfe5f1", background: ratio === r ? "#0b1a3a" : "#fff", color: ratio === r ? "#fff" : "#0b1a3a", borderRadius: 8, padding: "6px 12px", cursor: "pointer", fontWeight: 700 }}>
            {r}
          </button>
        ))}
        <span style={{ margin: "0 6px", opacity: 0.6, fontSize: 13 }}>variants</span>
        <select value={variants} onChange={(e) => setVariants(+e.target.value)} style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid #dfe5f1", font: "inherit" }}>
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>

      <button onClick={run} disabled={busy} style={{ background: "#00a3e0", color: "#fff", border: "none", borderRadius: 10, padding: "12px 22px", fontWeight: 800, cursor: "pointer", fontSize: 15 }}>
        {busy ? "Starting…" : "Generate variants"}
      </button>
      <div style={{ fontSize: 12, opacity: 0.55, marginTop: 12 }}>
        Local planner locks distinct stories + asset sets in ms → images land as soon as the image model returns (~seconds) → judge/fix + layer extraction polish in the background.
      </div>
    </div>
  );
}
