import { fileUrl } from "../lib/fileUrl";
import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function CatalogPanel() {
  const [assets, setAssets] = useState([]);
  const [grammar, setGrammar] = useState(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.catalog().then(setAssets).catch(() => {});
    api.grammar().then(setGrammar).catch(() => {});
  }, []);

  const filtered = assets.filter(
    (a) => !q || `${a.name} ${a.tags} ${a.semantic} ${a.role_hints} ${a.usage}`.toLowerCase().includes(q.toLowerCase())
  );

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16 }}>
      <div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search assets (tags, semantics, usage)"
          style={{ width: "100%", padding: 10, borderRadius: 10, border: "1px solid #dfe5f1", marginBottom: 12, font: "inherit" }}
        />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 12 }}>
          {filtered.map((a) => (
            <div key={a.id} style={{ background: "#fff", borderRadius: 12, overflow: "hidden", border: "1px solid #dfe5f1" }}>
              {a.png ? (
                <img src={fileUrl(a.png)} alt={a.name} style={{ width: "100%", height: 110, objectFit: "contain", background: "#fafafa" }} />
              ) : (
                <div style={{ height: 110, background: "#fafafa", display: "flex", alignItems: "center", justifyContent: "center", opacity: 0.5, fontSize: 12 }}>no raster preview</div>
              )}
              <div style={{ padding: 8, fontSize: 12 }}>
                <div style={{ fontWeight: 700 }}>{a.name.slice(0, 22)}</div>
                <div style={{ opacity: 0.65 }}>{a.kind} · {a.semantic || a.tags.slice(0, 2).join(" ")}</div>
              </div>
            </div>
          ))}
          {!filtered.length && <div style={{ opacity: 0.5 }}>No assets match.</div>}
        </div>
      </div>
      <aside style={{ background: "#fff", border: "1px solid #dfe5f1", borderRadius: 16, padding: 14, overflow: "auto", maxHeight: "80vh" }}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>Grammar</div>
        {!grammar && <div style={{ opacity: 0.5 }}>Run ingest to extract.</div>}
        {grammar && (
          <>
            <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 10 }}>{grammar.brand}</div>
            <Section title={`Recipes (${grammar.recipes?.length || 0})`}>
              {(grammar.recipes || []).map((r) => (
                <div key={r.id} style={{ marginBottom: 8 }}>
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{r.name}</div>
                  <div style={{ fontSize: 11, opacity: 0.7 }}>{r.intent}</div>
                  <div style={{ fontSize: 11 }}>{(r.slots || []).map((s) => s.role).join(" · ")}</div>
                </div>
              ))}
            </Section>
            <Section title={`Lexicon (${grammar.lexicon?.length || 0})`}>
              {(grammar.lexicon || []).slice(0, 14).map((e, i) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 4 }}>
                  <b>{e.name}</b> — {e.semantic || e.family}
                </div>
              ))}
            </Section>
            <Section title={`Techniques (${grammar.techniques?.length || 0})`}>
              {(grammar.techniques || []).slice(0, 10).map((t, i) => (
                <div key={i} style={{ fontSize: 12, marginBottom: 6 }}>
                  <b>{t.name}:</b> {t.instruction}
                </div>
              ))}
            </Section>
          </>
        )}
      </aside>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontWeight: 700, fontSize: 12, textTransform: "uppercase", opacity: 0.5, marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}
