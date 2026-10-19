import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import CanvasEditor from "../components/CanvasEditor";

export default function EditPage() {
  const { brandId, jobId, editId } = useParams();
  const nav = useNavigate();
  const [job, setJob] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const pollRef = useRef(null);

  const load = async () => {
    const j = await api.job(brandId, jobId);
    setJob(j);
    try {
      const m = await api.manifest(brandId, jobId, editId);
      setManifest(m);
    } catch {
      setManifest(null);
    }
  };

  useEffect(() => {
    load();
    return () => clearTimeout(pollRef.current);
  }, [brandId, jobId, editId]);

  useEffect(() => {
    const j = job;
    if (j?.status === "editing") {
      pollRef.current = setTimeout(async () => {
        await load();
        const jj = await api.job(brandId, jobId);
        const last = (jj.edits || [])[jj.edits.length - 1];
        if (jj.status === "done" && last && last.id !== editId) {
          nav(`/b/${brandId}/j/${jobId}/e/${last.id}`);
        }
      }, 2500);
    }
    return () => clearTimeout(pollRef.current);
  }, [job?.status, editId]);

  const applyEdit = async () => {
    if (!instruction.trim() || busy) return;
    setBusy(true);
    try {
      await api.createEdit(brandId, jobId, editId, instruction.trim());
      setInstruction("");
      const j = await api.job(brandId, jobId);
      setJob({ ...j, status: "editing" });
    } finally {
      setBusy(false);
    }
  };

  const drafts = job?.edits || [];
  const current = drafts.find((d) => d.id === editId);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", minHeight: "100%" }}>
      <aside style={{ borderRight: "1px solid #dfe5f1", padding: 16, overflow: "auto", background: "#fff" }}>
        <div style={{ fontWeight: 800, marginBottom: 8 }}>Drafts</div>
        <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
          {drafts.map((d) => (
            <Link
              key={d.id}
              to={`/b/${brandId}/j/${jobId}/e/${d.id}`}
              style={{
                padding: "8px 10px",
                borderRadius: 8,
                border: "1px solid #e6ecf7",
                background: d.id === editId ? "#e8efff" : "#f7f9fd",
                textDecoration: "none",
                color: "#0b1a3a",
                fontSize: 13,
              }}
            >
              <b>{d.id}</b>
              {d.parent ? <span style={{ opacity: 0.55 }}> ← {d.parent}</span> : <span style={{ opacity: 0.55 }}> (generated)</span>}
              <div style={{ opacity: 0.65, fontSize: 11, marginTop: 2 }}>{(d.instruction || d.kind).slice(0, 56)}</div>
            </Link>
          ))}
        </div>

        <div style={{ fontWeight: 800, marginBottom: 6 }}>Apply edit</div>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          rows={4}
          placeholder={"e.g. change headline to 'Books done. Life on.' · make the background deeper navy · add the beekeeper asset top-right"}
          style={{ width: "100%", borderRadius: 10, border: "1px solid #dfe5f1", padding: 10, font: "inherit", resize: "vertical" }}
        />
        <button
          onClick={applyEdit}
          disabled={busy || !instruction.trim() || job?.status === "editing"}
          style={{ marginTop: 8, width: "100%", background: "#00a3e0", color: "#fff", border: "none", borderRadius: 10, padding: "10px 12px", fontWeight: 800, cursor: "pointer" }}
        >
          {job?.status === "editing" ? "Editing…" : busy ? "Sending…" : `Edit from ${editId}`}
        </button>
        <div style={{ fontSize: 11, opacity: 0.55, marginTop: 8 }}>
          Text edits update live layers instantly. Visual edits repaint the design raster (never text).
          Asset requests ("add the coins", "put the logo top-right") RAG-search the brand catalog and paste the exact asset.
          {current?.kind && <div style={{ marginTop: 4 }}>current: {current.kind}</div>}
          {(current?.notes || []).map((n, i) => (
            <div key={i} style={{ marginTop: 2, opacity: 0.8 }}>· {n}</div>
          ))}
        </div>
      </aside>
      <section style={{ padding: 16, overflow: "auto" }}>
        {manifest?.pending_layers && (
          <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 10, padding: "8px 12px", fontSize: 12, marginBottom: 12 }}>
            ⚡ finishing layer extraction in the background — first edit will wait a few seconds for live layers, then apply.
          </div>
        )}
        <CanvasEditor job={job} manifest={manifest} variantId={job?.selected} />
      </section>
    </div>
  );
}
