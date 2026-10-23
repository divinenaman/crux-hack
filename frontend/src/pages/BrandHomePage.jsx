import React, { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileUrl } from "../api";
import { zoomProps } from "../lib/zoom";

function TreeNode({ node, depth = 0, active, onPick }) {
  return (
    <div>
      <div
        onClick={() => onPick(node.path)}
        style={{
          padding: "6px 8px",
          marginLeft: depth * 14,
          borderRadius: 8,
          cursor: "pointer",
          background: active === node.path ? "#e8efff" : "transparent",
          fontWeight: 600,
          fontSize: 13,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>📁 {node.name || "(root)"}</span>
        <span style={{ opacity: 0.55 }}>{node.count}</span>
      </div>
      {(node.children || []).map((c) => (
        <TreeNode key={c.path} node={c} depth={depth + 1} active={active} onPick={onPick} />
      ))}
    </div>
  );
}

export default function BrandHomePage() {
  const { brandId } = useParams();
  const [brand, setBrand] = useState(null);
  const [folder, setFolder] = useState("");
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [color, setColor] = useState("");
  const [useCase, setUseCase] = useState("");
  const [mismatch, setMismatch] = useState(0);
  const [assets, setAssets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [ingestState, setIngestState] = useState({ running: false, log: [], result: null });
  const [rootPath, setRootPath] = useState("");
  const fileRef = useRef(null);

  const load = () => {
    api.brand(brandId).then(setBrand).catch(() => setBrand(null));
    api.assets(brandId, { folder, q, kind, color, use_case: useCase, mismatch }).then(setAssets).catch(() => setAssets([]));
  };

  useEffect(load, [brandId, folder, q, kind, color, useCase, mismatch]);

  useEffect(() => {
    let stop = false;
    let timer;
    let wasRunning = false;
    const tick = async () => {
      try {
        const st = await api.ingestStatus(brandId);
        if (!stop) setIngestState(st);
        const flipped = wasRunning && !st.running && st.result;
        wasRunning = st.running;
        if (flipped && !stop) load();
      } catch {
        /* keep polling */
      }
      if (!stop) timer = setTimeout(tick, 1500);
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [brandId]);

  const startIngest = async (root) => {
    setBusy(true);
    try {
      await api.ingest(brandId, root || "");
      setIngestState((s) => ({ ...s, running: true }));
    } finally {
      setBusy(false);
    }
  };

  const uploadFiles = async (e) => {
    const files = e.target.files;
    if (!files?.length) return;
    setBusy(true);
    try {
      await api.upload(brandId, files);
      setIngestState((s) => ({ ...s, running: true }));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const idx = ingestState.result;
  const lastLog = (ingestState.log || []).slice(-3);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", minHeight: "100%" }}>
      <aside style={{ borderRight: "1px solid #dfe5f1", padding: 16, overflow: "auto", background: "#fff" }}>
        <div style={{ fontWeight: 800, marginBottom: 4 }}>{brand?.name || brandId}</div>
        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 12 }}>
          {brand?.assets ?? "…"} assets · {brand?.jobs?.length ?? "…"} jobs
        </div>
        <Link to={`/b/${brandId}/new`} style={{ display: "block", textAlign: "center", background: "#00a3e0", color: "#fff", padding: "10px 12px", borderRadius: 10, fontWeight: 700, textDecoration: "none", marginBottom: 14 }}>
          + Create image
        </Link>
        <button onClick={() => startIngest("")} disabled={busy || ingestState.running} style={{ width: "100%", marginBottom: 8, ...btn }}>
          {ingestState.running ? "Indexing…" : "Re-ingest / index assets"}
        </button>

        <div style={{ border: "1px solid #e6ecf7", borderRadius: 12, padding: 10, marginBottom: 14, background: "#f7f9fd" }}>
          <div style={{ fontWeight: 800, marginBottom: 6, fontSize: 13 }}>+ Add assets</div>
          <label style={{ display: "block", width: "100%", textAlign: "center", background: "#00a3e0", color: "#fff", padding: "8px 10px", borderRadius: 8, fontWeight: 700, cursor: "pointer", fontSize: 13, marginBottom: 8 }}>
            Upload images…
            <input ref={fileRef} type="file" multiple accept=".png,.jpg,.jpeg,.webp,.svg,image/*" onChange={uploadFiles} style={{ display: "none" }} />
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              value={rootPath}
              onChange={(e) => setRootPath(e.target.value)}
              placeholder="…or folder path to index"
              style={{ ...inp, flex: 1, minWidth: 0, fontSize: 12 }}
            />
            <button onClick={() => startIngest(rootPath)} disabled={busy || ingestState.running || !rootPath.trim()} style={{ ...btn, padding: "6px 10px", fontSize: 12 }}>
              Index
            </button>
          </div>
          <div style={{ marginTop: 8, fontSize: 11, minHeight: 34 }}>
            {ingestState.running ? (
              <span style={{ color: "#00a3e0", fontWeight: 700 }}>
                ⚡ indexing in background…
                {lastLog.map((m, i) => (
                  <div key={i} style={{ opacity: 0.65, fontWeight: 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>· {m}</div>
                ))}
              </span>
            ) : ingestState.error ? (
              <span style={{ color: "#b91c1c" }}>✗ {ingestState.error}</span>
            ) : idx ? (
              <span style={{ color: "#15803d" }}>✓ {idx.assets} assets indexed · {idx.usable} usable</span>
            ) : (
              <span style={{ opacity: 0.55 }}>png / jpg / webp / svg — runs in the background</span>
            )}
          </div>
        </div>

        <div style={{ fontWeight: 700, margin: "8px 0" }}>Asset classes</div>
        <div onClick={() => setFolder("")} style={{ padding: "6px 8px", borderRadius: 8, cursor: "pointer", background: folder === "" ? "#e8efff" : "transparent", fontWeight: 700, fontSize: 13 }}>
          All
        </div>
        {(brand?.tree || []).map((n) => (
          <TreeNode key={n.path} node={n} active={folder} onPick={setFolder} />
        ))}

        {brand?.rules && (
          <div style={{ marginTop: 18, fontSize: 11, background: "#f7f9fd", border: "1px solid #e6ecf7", borderRadius: 10, padding: 10 }}>
            <div style={{ fontWeight: 800, marginBottom: 6 }}>Brand rules (indexed)</div>
            {(brand.rules.context_rules || []).slice(0, 6).map((r, i) => (
              <div key={i} style={{ marginBottom: 4 }}>· <b>{r.name}</b>: {r.then}</div>
            ))}
            {(brand.rules.donts || []).slice(0, 4).map((d, i) => (
              <div key={`d${i}`} style={{ opacity: 0.7 }}>✗ {d}</div>
            ))}
          </div>
        )}
      </aside>

      <section style={{ padding: 18, overflow: "auto" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search name / semantic / tags" style={{ ...inp, minWidth: 220 }} />
          <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="type (logo, charm…)" style={inp} />
          <input value={color} onChange={(e) => setColor(e.target.value)} placeholder="colour" style={inp} />
          <input value={useCase} onChange={(e) => setUseCase(e.target.value)} placeholder="use case" style={inp} />
          <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={!!mismatch} onChange={(e) => setMismatch(e.target.checked ? 1 : 0)} /> mismatches only
          </label>
        </div>
        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 10 }}>
          {folder ? `class: ${folder}` : "all classes"} · {assets.length} indexed
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 12 }}>
          {assets.map((a) => (
            <div key={a.id} style={{ background: "#fff", border: "1px solid #dfe5f1", borderRadius: 12, overflow: "hidden" }}>
              {a.png ? (
                <img
                  src={fileUrl(a.png)}
                  alt={a.name}
                  title="click to zoom"
                  {...zoomProps(fileUrl(a.png), a.name)}
                  style={{ width: "100%", height: 120, objectFit: "contain", background: "#f4f6fb" }}
                />
              ) : (
                <div style={{ height: 120, background: "#f4f6fb" }} />
              )}
              <div style={{ padding: 10, fontSize: 12 }}>
                <div style={{ fontWeight: 700 }}>{a.name.slice(0, 30)}</div>
                <div style={{ opacity: 0.6 }}>{a.kind} · {a.folder || "(root)"}</div>
                <div style={{ marginTop: 4, opacity: 0.8 }}>{a.semantic}</div>
                <div style={{ marginTop: 4, display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {(a.colors || []).slice(0, 4).map((c) => (
                    <span key={c} style={{ background: c, width: 14, height: 14, borderRadius: 4, border: "1px solid #ddd" }} />
                  ))}
                </div>
                <div style={{ marginTop: 4, opacity: 0.65 }}>uses: {(a.use_cases || []).slice(0, 3).join(", ")}</div>
                {!!(a.mismatches || []).length && (
                  <div style={{ marginTop: 4, color: "#b91c1c" }}>⚠ {a.mismatches[0]}</div>
                )}
                <div style={{ marginTop: 4, opacity: 0.5 }}>rules: {(a.rule_refs || []).slice(0, 2).join(", ") || "—"}</div>
              </div>
            </div>
          ))}
        </div>

        {!!(brand?.jobs || []).length && (
          <>
            <h3 style={{ marginTop: 26 }}>Jobs</h3>
            <div style={{ display: "grid", gap: 8 }}>
              {brand.jobs.map((j) => (
                <Link key={j.id} to={`/b/${brandId}/j/${j.id}`} style={{ padding: "10px 14px", border: "1px solid #dfe5f1", borderRadius: 10, background: "#fff", textDecoration: "none", color: "#0b1a3a", display: "flex", justifyContent: "space-between" }}>
                  <span>{(j.use_case || j.id).slice(0, 70)}</span>
                  <span style={{ opacity: 0.6, fontSize: 12 }}>{j.status}{j.folder ? ` · ${j.folder}` : ""}</span>
                </Link>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

const btn = { borderRadius: 10, padding: "10px 12px", cursor: "pointer", fontWeight: 700, border: "1px solid #dfe5f1", background: "#fff" };
const inp = { padding: "8px 10px", borderRadius: 8, border: "1px solid #dfe5f1", font: "inherit", fontSize: 13 };
