import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileUrl } from "../api";

export default function JobsPage() {
  const { brandId } = useParams();
  const [jobs, setJobs] = useState([]);

  useEffect(() => {
    api.jobs(brandId).then(setJobs).catch(() => setJobs([]));
  }, [brandId]);

  return (
    <div style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Jobs</h2>
        <Link to={`/b/${brandId}/new`} style={{ background: "#00a3e0", color: "#fff", padding: "10px 16px", borderRadius: 10, fontWeight: 800, textDecoration: "none" }}>+ Create image</Link>
      </div>
      <div style={{ display: "grid", gap: 12 }}>
        {jobs.map((j) => (
          <div key={j.id} style={{ display: "grid", gridTemplateColumns: "84px 1fr auto", gap: 14, alignItems: "center", background: "#fff", border: "1px solid #dfe5f1", borderRadius: 14, padding: 12 }}>
            {j.image ? (
              <img src={fileUrl(j.image)} alt="" style={{ width: 84, height: 84, objectFit: "cover", borderRadius: 10, background: "#f4f6fb" }} />
            ) : (
              <div style={{ width: 84, height: 84, borderRadius: 10, background: "#f4f6fb" }} />
            )}
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{(j.use_case || j.id).slice(0, 90)}</div>
              <div style={{ fontSize: 12, opacity: 0.65, marginTop: 4 }}>
                {j.status}{j.folder ? ` · ${j.folder}` : ""} · {j.n_variants} variants · {j.n_edits} edits · {j.ratio}
              </div>
              {!!j.error && <div style={{ fontSize: 12, color: "#b91c1c", marginTop: 2 }}>{String(j.error).slice(0, 80)}</div>}
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <Link to={`/b/${brandId}/j/${j.id}`} style={btn}>Open</Link>
              {j.status === "done" && (
                <Link to={`/b/${brandId}/j/${j.id}/e/generated`} style={{ ...btn, background: "#00a3e0", color: "#fff", border: "none" }}>Edit</Link>
              )}
            </div>
          </div>
        ))}
        {!jobs.length && <div style={{ opacity: 0.5, padding: 30, textAlign: "center" }}>No jobs yet.</div>}
      </div>
    </div>
  );
}

const btn = { padding: "8px 14px", borderRadius: 8, border: "1px solid #dfe5f1", fontWeight: 700, textDecoration: "none", color: "#0b1a3a", fontSize: 13 };
