import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import TrailPanel from "../components/TrailPanel";
import VariantGallery from "../components/VariantGallery";

export default function JobPage() {
  const { brandId, jobId } = useParams();
  const [job, setJob] = useState(null);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const j = await api.job(brandId, jobId);
        if (!stop) setJob(j);
        if (j.status !== "done" && j.status !== "failed") setTimeout(tick, 2500);
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

  return (
    <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", minHeight: "100%" }}>
      <aside style={{ borderRight: "1px solid #dfe5f1", padding: 16, overflow: "auto", background: "#fff" }}>
        <div style={{ fontWeight: 800, marginBottom: 6 }}>
          Generation {job?.status && job.status !== "done" ? <span style={{ color: "#00a3e0" }}>· {job.status}</span> : ""}
        </div>
        <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 10 }}>
          {(job?.use_case || "").slice(0, 120)}
          {job?.folder ? ` · class ${job.folder}` : ""}
        </div>
        <div style={{ fontSize: 11, whiteSpace: "pre-wrap", background: "#f4f6fb", borderRadius: 10, padding: 10, maxHeight: 120, overflow: "auto", marginBottom: 12 }}>
          {(job?.log || ["ready"]).slice(-10).join("\n")}
        </div>
        <div style={{ fontWeight: 700, margin: "8px 0" }}>Progressive steps</div>
        <TrailPanel job={job} />
      </aside>
      <section style={{ padding: 18, overflow: "auto" }}>
        {done && gen && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", background: "#e8efff", border: "1px solid #c7d2fe", borderRadius: 12, padding: "12px 16px", marginBottom: 16 }}>
            <div style={{ fontWeight: 700 }}>Final image ready — editable layered canvas</div>
            <Link to={`/b/${brandId}/j/${jobId}/e/generated`} style={{ background: "#00a3e0", color: "#fff", padding: "10px 18px", borderRadius: 10, fontWeight: 800, textDecoration: "none" }}>
              Edit →
            </Link>
          </div>
        )}
        <VariantGallery job={job} selected={job?.selected} onPick={() => {}} />
        {job?.error && <div style={{ color: "#b91c1c", marginTop: 12 }}>{job.error}</div>}
      </section>
    </div>
  );
}
