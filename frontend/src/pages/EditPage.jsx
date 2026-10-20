import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import CanvasEditor from "../components/CanvasEditor";
import { fileUrl } from "../lib/fileUrl";
import { zoomProps } from "../lib/zoom";

const OP_COLOR = {
  change_text: "#2E7CF6",
  add_text: "#2E7CF6",
  change_color: "#FF7EB6",
  reposition: "#4ADE80",
  change_asset: "#FFD84D",
  add_asset: "#FFD84D",
  remove: "#ef4444",
  edit: "#8b5cf6",
  change_background: "#00a3e0",
};

function ModeBadge({ mode }) {
  if (!mode) return null;
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 800,
        letterSpacing: 0.3,
        textTransform: "uppercase",
        borderRadius: 4,
        padding: "1px 5px",
        marginLeft: 6,
        background: mode === "generated" ? "#ede9fe" : "#f1f5f9",
        color: mode === "generated" ? "#6d28d9" : "#64748b",
      }}
    >
      {mode}
    </span>
  );
}

function opLine(op) {
  const r = op.role ? ` · ${op.role}` : "";
  const rect = op.rect ? ` @ [${op.rect.map((v) => Number(v).toFixed(2)).join(", ")}]` : "";
  switch (op.op) {
    case "change_text":
      return (
        <span>
          change_text{r} → "{(op.content || "").slice(0, 48)}"
          <ModeBadge mode={op.mode} />
        </span>
      );
    case "add_text":
      return (
        <span>
          add_text{r} → "{(op.content || "").slice(0, 48)}"{rect}
          <ModeBadge mode={op.mode} />
        </span>
      );
    case "change_color":
      return `change_color${r} → ${op.color}`;
    case "reposition":
      return `reposition${r} →${rect}`;
    case "change_asset":
      return `change_asset${r} ← ${op.asset_id ? `#${op.asset_id}` : `"${op.query}"`}${rect}`;
    case "add_asset":
      return `add_asset · ${op.asset_id ? `#${op.asset_id}` : `"${op.query}"`}${rect}`;
    case "remove":
      return `remove${r}`;
    case "change_background":
      return `change_background · "${(op.prompt || "").slice(0, 64)}"`;
    default: {
      const bits = ["content", "color", "rect", "query", "asset_id", "size_scale"].filter((k) => op[k] !== undefined);
      return `edit${r} · ${bits.join("+")}`;
    }
  }
}

function EditRecipe({ draft }) {
  const [copied, setCopied] = useState(false);
  if (!draft || (!(draft.ops || []).length && !draft.fill_prompt)) return null;
  const wire = fileUrl(draft.ref_image);
  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(draft.fill_prompt || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked — text stays selectable */
    }
  };
  return (
    <div style={{ background: "#fff", border: "1px solid #dfe5f1", borderRadius: 14, padding: 14, marginBottom: 12, boxShadow: "0 4px 14px rgba(11,26,58,0.05)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontWeight: 800, fontSize: 13 }}>Edit recipe</span>
        {draft.kind && (
          <span style={{ fontSize: 11, fontWeight: 800, background: "#eaf7ff", color: "#0369a1", borderRadius: 999, padding: "3px 10px" }}>{draft.kind}</span>
        )}
      </div>
      <div style={{ display: "grid", gap: 4 }}>
        {(draft.ops || []).map((op, i) => (
          <div key={i} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 12, fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
            <span style={{ width: 8, height: 8, borderRadius: 99, background: OP_COLOR[op.op] || "#94a3b8", flex: "0 0 auto", transform: "translateY(-1px)" }} />
            <span style={{ color: "#1e293b", wordBreak: "break-word" }}>{opLine(op)}</span>
          </div>
        ))}
      </div>
      {draft.fill_prompt && (
        <div style={{ marginTop: 12, border: "1px solid #e6ecf7", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: "#f7f9fd", borderBottom: "1px solid #e6ecf7" }}>
            <span style={{ fontWeight: 800, fontSize: 12 }}>Background prompt (re-painted on the updated layout)</span>
            <button
              onClick={copyPrompt}
              style={{
                border: copied ? "1px solid #34d399" : "1px solid #dfe5f1",
                background: copied ? "#ecfdf5" : "#fff",
                color: copied ? "#15803d" : "#0b1a3a",
                borderRadius: 8,
                padding: "4px 10px",
                fontSize: 11,
                fontWeight: 800,
                cursor: "pointer",
              }}
            >
              {copied ? "copied ✓" : "copy prompt"}
            </button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 140px", gap: 10, padding: 10 }}>
            <pre
              style={{
                margin: 0,
                maxHeight: 180,
                overflow: "auto",
                fontSize: 11,
                lineHeight: 1.5,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                color: "#1e293b",
              }}
            >
              {draft.fill_prompt}
            </pre>
            <div>
              {wire && (
                <img
                  src={wire}
                  alt="updated wireframe reference"
                  title="click to zoom — the reference sent to the model"
                  {...zoomProps(wire, "edit wireframe reference")}
                  style={{ width: "100%", display: "block", borderRadius: 8, border: "1px solid #e6ecf7", cursor: "zoom-in" }}
                />
              )}
              <div style={{ fontSize: 10.5, opacity: 0.6, marginTop: 4 }}>updated layout sent as reference</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

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
          Your prompt becomes typed layer instructions: edit · remove · reposition · change-text ·
          change-asset · change-color — or change_background, which re-prompts the artwork on the
          updated wireframe (prompt + reference shown under the canvas).
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
        <EditRecipe draft={current} />
        <CanvasEditor job={job} manifest={manifest} variantId={job?.selected} />
      </section>
    </div>
  );
}
