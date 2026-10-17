import React from "react";

const CHECK_LABEL = {
  copy_fidelity: "Copy fidelity",
  text_free_clean: "Clean text-free zones",
  asset_fidelity: "Asset identity",
  brand_rules: "Brand rules",
  technique: "Technique use",
  artifacts: "Artifacts",
  composition: "Composition",
};

const labelFor = (check) => {
  if (CHECK_LABEL[check]) return CHECK_LABEL[check];
  if (check?.startsWith("asset_match:")) {
    const id = check.slice("asset_match:".length);
    return `Asset present: …${id.slice(-24)}`;
  }
  return check;
};

export default function JudgeDiffPanel({ variant, brief }) {
  const reports = variant?.reports || [];
  const best = variant?.best_report || reports[reports.length - 1];
  const fails = (best?.items || []).filter((i) => !i.pass);
  const passes = (best?.items || []).filter((i) => i.pass);

  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>
        Judge diff {best?.score != null && <span style={{ color: "#00a3e0" }}>· score {best.score}</span>}
      </div>

      {reports.length > 1 && (
        <div style={{ display: "flex", gap: 4, marginBottom: 10, flexWrap: "wrap" }}>
          {reports.map((r, i) => (
            <span key={i} style={{ background: r === best ? "#e8efff" : "#f4f6fb", border: "1px solid #e6ebf5", borderRadius: 6, padding: "2px 6px", fontWeight: 700 }}>
              r{i + 1}: {r.score}
            </span>
          ))}
        </div>
      )}

      {brief?.story && (
        <div style={{ background: "#eef2ff", border: "1px solid #c7d2fe", borderRadius: 10, padding: 8, marginBottom: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Idea cohort</div>
          <div style={{ fontWeight: 600 }}>{brief.archetype}</div>
          <div style={{ opacity: 0.85, marginTop: 2 }}>{brief.story}</div>
          {brief.idea && <div style={{ opacity: 0.7, marginTop: 2 }}>concept: {brief.idea}</div>}
          {brief.color_story && <div style={{ opacity: 0.7, marginTop: 2 }}>colour: {brief.color_story}</div>}
        </div>
      )}

      {brief?.copy && (
        <div style={{ background: "#f7f9fd", border: "1px solid #e6ebf5", borderRadius: 10, padding: 8, marginBottom: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>Expected copy</div>
          <div style={{ fontWeight: 600 }}>{brief.copy.headline}</div>
          {brief.copy.sub && <div style={{ opacity: 0.7 }}>{brief.copy.sub}</div>}
          {(brief.copy.body || []).map((b, i) => (
            <div key={i} style={{ opacity: 0.7 }}>· {b}</div>
          ))}
          {brief.copy.cta && <div style={{ marginTop: 2, fontWeight: 600 }}>CTA: {brief.copy.cta}</div>}
        </div>
      )}

      {brief?.violations?.length > 0 && (
        <div style={{ background: "#fff7ed", border: "1px solid #fed7aa", borderRadius: 10, padding: 8, marginBottom: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 4, color: "#c2410c" }}>Brief warnings</div>
          {brief.violations.map((v, i) => (
            <div key={i} style={{ opacity: 0.85 }}>· {v}</div>
          ))}
        </div>
      )}

      <div style={{ fontWeight: 700, margin: "8px 0 6px", color: "#b91c1c" }}>Differences to fix ({fails.length})</div>
      {fails.length === 0 && <div style={{ color: "#15803d", marginBottom: 10 }}>All checks passing.</div>}
      {fails.map((f, i) => (
        <div key={i} style={{ border: "1px solid #fecaca", background: "#fef2f2", borderRadius: 10, padding: 8, marginBottom: 8 }}>
          <div style={{ fontWeight: 700, color: "#b91c1c" }}>✗ {labelFor(f.check)}</div>
          {f.note && <div style={{ marginTop: 3 }}>{f.note}</div>}
          {f.fix_prompt && (
            <div style={{ marginTop: 4, opacity: 0.75, fontStyle: "italic" }}>
              fix sent to image model: “{f.fix_prompt}”
            </div>
          )}
          {(variant?.brief?.slots || [])
            .filter((s) => f.check?.includes(s.asset_id))
            .map((s, j) => (
              <div key={j} style={{ marginTop: 4, fontSize: 11, opacity: 0.75 }}>
                <b>asset reason:</b> {s.why || "—"} · <b>planned:</b> {s.placement || "—"}
              </div>
            ))}
        </div>
      ))}

      <div style={{ fontWeight: 700, margin: "10px 0 6px", color: "#15803d" }}>Passing ({passes.length})</div>
      <div style={{ opacity: 0.75 }}>
        {passes.map((p, i) => (
          <div key={i}>✓ {labelFor(p.check)}</div>
        ))}
        {!passes.length && <div>—</div>}
      </div>
    </div>
  );
}
