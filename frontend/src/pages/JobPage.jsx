import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import TrailPanel from "../components/TrailPanel";
import VariantGallery from "../components/VariantGallery";

const STAGE_TEXT = {
  pending: "queued…",
  briefing: "designing concepts · LLM wants + retrieval",
  composing: "composing images · flux-1-schnell",
  judging: "judging design",
  fixing: "applying fixes",
  selecting: "selecting winner",
  delivering: "extracting layers · stripping text",
  editing: "applying edit",
};

export default function JobPage() {
  const { brandId, jobId } = useParams();
  const [job, setJob] = useState(null);
  const [manifest, setManifest] = useState(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.job(brandId, jobId);
        if (!stop) setJob(j);
        const gen = (j.edits || []).find((e) => e.id === "generated");
        if (gen) {
          api.manifest(brandId, jobId, "generated").then((m) => !stop && setManifest(m)).catch(() => {});
        }
        const active = (j.status !== "done" && j.status !== "failed") || j.refining;
        if (active) setTimeout(tick, j.refining ? 3000 : 1500);
      } catch {
        setTimeout(tick, 4000);
      }
    };
    tick();
    return () => {
      stop = true;
    };
  }, [brandId, jobId]);

  const done = job?.status === "done";
  const gen = (job?.edits || []).find((e) => e.id === "generated");
  const working = job && job.status !== "done" && job.status !== "failed";
  const stageText = job?.refining
    ? "polishing · judging · stripping text · measuring layers"
    : STAGE_TEXT[job?.status] || job?.status || "starting…";
  const lastLogs = (job?.log || []).slice(-3);
  const layers = (manifest?.layers || []).filter((l) => l.type !== "raster");

  return (
    <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", minHeight: "100%" }}>
      <aside style={{ borderRight: "1px solid #dfe5f1", padding: 16, overflow: "auto", background: "#fff" }}>
        <div style={{ fontWeight: 800, marginBottom: 6 }}>
          Generation {job?.status && job.status !== "done" ? <span style={{ color: "#00a3e0" }}>· {job.status}</span> : ""}
          {job?.refining ? <span style={{ color: "#a855f7" }}> · polishing</span> : ""}
        </div>
        <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 10 }}>
          {(job?.use_case || "").slice(0, 120)}
          {job?.folder ? ` · class ${job.folder}` : ""}
        </div>
        <div style={{ fontWeight: 700, margin: "8px 0" }}>Progressive steps</div>
        <TrailPanel job={job} />
      </aside>
      <section style={{ padding: 18, overflow: "auto" }}>
        {(working || job?.refining) && (
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start", background: "#eef4ff", border: "1px solid #c7d2fe", borderRadius: 12, padding: "12px 16px", marginBottom: 16 }}>
            <span className="spin" style={{ marginTop: 2 }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800 }}>{stageText}</div>
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4, fontFamily: "ui-monospace, monospace" }}>
                {lastLogs.map((l, i) => (
                  <div key={i} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>· {l}</div>
                ))}
                {!lastLogs.length && "warming up…"}
              </div>
            </div>
          </div>
        )}
        {done && gen && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#e8efff", border: "1px solid #c7d2fe", borderRadius: 12, padding: "12px 16px", marginBottom: 12 }}>
            <div style={{ fontWeight: 700 }}>Final image ready — editable layered canvas</div>
            <Link to={`/b/${brandId}/j/${jobId}/e/generated`} style={{ background: "#00a3e0", color: "#fff", padding: "10px 18px", borderRadius: 10, fontWeight: 800, textDecoration: "none" }}>
              Edit →
            </Link>
          </div>
        )}
        {gen && layers.length > 0 && (
          <div style={{ background: "#fff", border: "1px solid #dfe5f1", borderRadius: 12, padding: "12px 16px", marginBottom: 16 }}>
            <div style={{ fontWeight: 800, marginBottom: 8 }}>
              Layers extracted ({layers.length})
              {manifest?.pending_layers && <span style={{ color: "#a855f7", fontSize: 12, fontWeight: 600 }}> · extracting…</span>}
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {layers.map((l, i) => (
                <Link
                  key={i}
                  to={`/b/${brandId}/j/${jobId}/e/${gen.id}`}
                  title={l.content || l.asset_id || l.src}
                  style={{ border: "1px solid #e6ecf7", borderRadius: 8, padding: "6px 10px", fontSize: 12, textDecoration: "none", color: "#0b1a3a", background: l.type === "text" ? "#eef2ff" : "#ecfdf5" }}
                >
                  <b>{l.role}</b>
                  <span style={{ opacity: 0.6 }}> · {l.type}</span>
                  <div style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", opacity: 0.75 }}>
                    {(l.content || l.asset_id || "").slice(0, 40)}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
        <VariantGallery job={job} selected={job?.selected} onPick={() => {}} />
        {job?.error && <div style={{ color: "#b91c1c", marginTop: 12 }}>{job.error}</div>}
      </section>
    </div>
  );
}
