import { fileUrl } from "../lib/fileUrl";
import React from "react";

export default function VariantGallery({ job, selected, onPick }) {
  if (!job?.variants?.length) {
    return (
      <div style={{ opacity: 0.55, padding: 40, textAlign: "center" }}>
        Run a use case to see judged variants here.
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
      {job.variants.map((v) => {
        const report = v.best_report;
        const fails = (report?.items || []).filter((i) => !i.pass).map((i) => i.check);
        return (
          <div
            key={v.id}
            onClick={() => onPick(v.id)}
            style={{
              background: "#fff",
              borderRadius: 16,
              overflow: "hidden",
              border: selected === v.id ? "2px solid #00a3e0" : "1px solid #dfe5f1",
              cursor: "pointer",
              boxShadow: "0 4px 14px rgba(11,26,58,0.06)",
            }}
          >
            {v.image ? (
              <img src={fileUrl(v.image)} alt={v.id} style={{ width: "100%", display: "block", aspectRatio: "1/1", objectFit: "cover", background: "#f4f6fb" }} />
            ) : (
              <div style={{ aspectRatio: "1/1", background: "#f4f6fb" }} />
            )}
            <div style={{ padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, gap: 8 }}>
                <span>{v.brief?.copy?.headline?.slice(0, 28) || v.id.split("_").pop()}</span>
                <span style={{ color: "#00a3e0" }}>{report?.score ?? "–"}</span>
              </div>
              <div style={{ fontSize: 12, opacity: 0.65, marginTop: 4 }}>{v.brief?.archetype} · {v.brief?.boldness}</div>
              {v.brief?.story && <div style={{ fontSize: 12, marginTop: 6 }}><b>story:</b> {v.brief.story.slice(0, 90)}</div>}
              {v.brief?.color_story && <div style={{ fontSize: 11, opacity: 0.7, marginTop: 2 }}><b>colour:</b> {v.brief.color_story.slice(0, 70)}</div>}
              <div style={{ fontSize: 11, marginTop: 6, color: fails.length ? "#c2410c" : "#15803d" }}>
                {fails.length ? `fails: ${fails.slice(0, 3).join(", ")}` : "all checks passed"}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
