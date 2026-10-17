import { fileUrl } from "../lib/fileUrl";
import React, { useEffect, useRef } from "react";


const STAGE_COLOR = {
  brief: "#6366f1",
  contact: "#0ea5e9",
  compose: "#00a3e0",
  judge: "#f59e0b",
  fix: "#f97316",
  variant: "#22c55e",
  select: "#0b1a3a",
  strip: "#14b8a6",
  tune: "#a855f7",
  manifest: "#8b5cf6",
};

const STAGE_LABEL = {
  brief: "BRIEF",
  contact: "ASSETS",
  compose: "COMPOSE",
  judge: "JUDGE",
  fix: "FIX",
  variant: "OUTPUT",
  select: "WINNER",
  strip: "STRIP",
  tune: "TUNE",
  manifest: "CANVAS",
};

export default function TrailPanel({ job }) {
  const endRef = useRef(null);
  const trail = job?.trail || [];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [trail.length]);

  if (!trail.length) {
    return (
      <div style={{ opacity: 0.45, fontSize: 12, padding: "8px 2px" }}>
        Trail will stream here: brief → assets → compose → judge → fix → canvas.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {trail.map((t) => (
        <div key={t.id} style={{ display: "grid", gridTemplateColumns: t.image ? "64px 1fr" : "1fr", gap: 10, alignItems: "start" }}>
          {t.image ? (
            <img
              src={fileUrl(t.image)}
              alt={t.stage}
              style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 8, border: "1px solid #dfe5f1", background: "#f7f9fd" }}
            />
          ) : (
            <div />
          )}
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 800,
                  letterSpacing: 0.6,
                  color: "#fff",
                  background: STAGE_COLOR[t.stage] || "#94a3b8",
                  borderRadius: 4,
                  padding: "2px 5px",
                }}
              >
                {STAGE_LABEL[t.stage] || t.stage.toUpperCase()}
              </span>
              {t.score != null && (
                <span style={{ fontSize: 11, fontWeight: 800, color: t.score >= 70 ? "#15803d" : t.score >= 50 ? "#c2410c" : "#b91c1c" }}>{t.score}</span>
              )}
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, marginTop: 2 }}>{t.label}</div>
            {(t.notes || []).slice(0, 3).map((n, i) => (
              <div key={i} style={{ fontSize: 11, opacity: 0.65, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                · {n}
              </div>
            ))}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
