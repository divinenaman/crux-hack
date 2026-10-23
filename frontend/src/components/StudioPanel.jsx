import React, { useEffect, useMemo, useState } from "react";
import { fileUrl } from "../lib/fileUrl";
import { zoomProps } from "../lib/zoom";

/**
 * Studio — how the background came to be:
 *   staged canvas: 1) text + assets placed (wireframe) → 2) generated image fills in
 *   side by side with the prepared prompt + reference image sent to the model.
 */
export default function StudioPanel({ job }) {
  const variants = useMemo(
    () => (job?.variants || []).filter((v) => v.image || v.ref_image || v.fill_prompt),
    [job]
  );
  const [vid, setVid] = useState("");
  const activeId = vid && variants.some((v) => v.id === vid) ? vid : job?.selected || variants[0]?.id || "";
  const v = variants.find((x) => x.id === activeId);

  // staged reveal: phase 0 = pieces placed (wireframe), phase 1 = background painted (final)
  const [phase, setPhase] = useState(0);
  const [auto, setAuto] = useState(0);
  useEffect(() => {
    if (!v) return;
    setPhase(0);
    const t = setTimeout(() => setPhase(1), 1300);
    return () => clearTimeout(t);
  }, [activeId, auto, v]);

  const [copied, setCopied] = useState(false);
  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(v?.fill_prompt || "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked — the text is selectable anyway */
    }
  };

  if (!v) return null;

  const background = fileUrl(v.history?.[0] || "");
  const layoutPreview = fileUrl(v.layout_image || v.ref_image);
  const modelReference = fileUrl(v.ref_image);
  const textToImage = v.fill_model?.includes("text-to-image");
  const aspectRatio = (v.brief?.ratio || job?.ratio || "1:1").replace(":", " / ");
  const steps = [
    { n: 1, label: "full layout (transparent)" },
    { n: 2, label: v.fill_error ? "flat-field fallback" : "background painted" },
  ];

  return (
    <div style={{ background: "#fff", border: "1px solid #dfe5f1", borderRadius: 18, padding: 18, marginBottom: 18, boxShadow: "0 6px 22px rgba(11,26,58,0.06)" }}>
      {/* variant chips */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontWeight: 800, fontSize: 15 }}>Studio</span>
          {variants.map((x) => (
            <button
              key={x.id}
              onClick={() => setVid(x.id)}
              style={{
                border: x.id === activeId ? "1.5px solid #00a3e0" : "1px solid #dfe5f1",
                background: x.id === activeId ? "#eaf7ff" : "#fff",
                color: "#0b1a3a",
                borderRadius: 999,
                padding: "5px 12px",
                fontSize: 12,
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              {x.id.split("_").pop()} · {(x.brief?.copy?.headline || x.prompt || "").slice(0, 26)}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{ display: "flex", border: "1px solid #dfe5f1", borderRadius: 999, overflow: "hidden" }}>
            {steps.map((s) => (
              <button
                key={s.n}
                onClick={() => setPhase(s.n - 1)}
                style={{
                  border: "none",
                  background: phase === s.n - 1 ? "#0b1a3a" : "#fff",
                  color: phase === s.n - 1 ? "#fff" : "#0b1a3a",
                  padding: "6px 12px",
                  fontSize: 12,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {s.n}. {s.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setAuto((a) => a + 1)}
            title="Replay the build"
            style={{ border: "1px solid #dfe5f1", background: "#fff", borderRadius: 999, padding: "6px 12px", fontSize: 12, fontWeight: 700, cursor: "pointer" }}
          >
            ⟳ replay
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.15fr) minmax(0,1fr)", gap: 18, alignItems: "start" }}>
        {/* ── staged canvas ── */}
        <div>
          <div
            style={{
              position: "relative",
              borderRadius: 14,
              overflow: "hidden",
              border: "1px solid #e6ecf7",
              background: "repeating-conic-gradient(#f4f6fb 0% 25%, #fff 0% 50%) 0 0/22px 22px",
              aspectRatio,
            }}
          >
            {/* The replay shows the exact model reference, then that same reference over its background. */}
            {phase === 1 && background && (
              <img src={background} alt="generated background" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" }} />
            )}
            {layoutPreview && (
              <img
                src={layoutPreview}
                alt={phase === 0 ? "transparent layout reference" : "layout reference over generated background"}
                style={{
                  position: "absolute",
                  inset: 0,
                  width: "100%",
                  height: "100%",
                  objectFit: "contain",
                }}
              />
            )}
            <div
              style={{
                position: "absolute",
                left: 12,
                bottom: 12,
                display: "flex",
                gap: 8,
                alignItems: "center",
                background: "rgba(11,26,58,0.82)",
                color: "#fff",
                borderRadius: 999,
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 700,
                backdropFilter: "blur(4px)",
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: 99, background: phase === 0 ? "#fbbf24" : "#34d399", display: "inline-block" }} />
              {phase === 0
                ? "1 · text + assets placed"
                : v.fill_error
                  ? "2 · image generation failed; flat-field fallback"
                  : "2 · background painted in"}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 10, fontSize: 12, opacity: 0.7, flexWrap: "wrap" }}>
            <span>
              <b>flow:</b> {textToImage
                ? "written art direction → image model paints the background → exact text + assets composited on top"
                : "wireframe (ref) → image model paints the whole background → real text + assets composited on top"}
            </span>
          </div>
        </div>

        {v.fill_error && (
          <div style={{ marginBottom: 14, padding: "10px 14px", border: "1px solid #fca5a5", borderRadius: 10, background: "#fef2f2", color: "#991b1b", fontSize: 12 }}>
            <b>No AI background was generated for this variant.</b> It is showing the flat-field fallback.
            <div style={{ marginTop: 4, opacity: 0.85 }}>{v.fill_error}</div>
          </div>
        )}

        {/* ── prompt + reference, side by side with the canvas ── */}
        <div style={{ display: "grid", gap: 14 }}>
          <div style={{ border: "1px solid #e6ecf7", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "#f7f9fd", borderBottom: "1px solid #e6ecf7" }}>
              <span style={{ fontWeight: 800, fontSize: 13 }}>Background prompt</span>
              <button
                onClick={copyPrompt}
                style={{
                  border: copied ? "1px solid #34d399" : "1px solid #dfe5f1",
                  background: copied ? "#ecfdf5" : "#fff",
                  color: copied ? "#15803d" : "#0b1a3a",
                  borderRadius: 8,
                  padding: "5px 12px",
                  fontSize: 12,
                  fontWeight: 800,
                  cursor: "pointer",
                }}
              >
                {copied ? "copied ✓" : "copy prompt"}
              </button>
            </div>
            <pre
              style={{
                margin: 0,
                padding: 14,
                maxHeight: 320,
                overflow: "auto",
                fontSize: 11.5,
                lineHeight: 1.55,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                color: "#1e293b",
                background: "#fff",
              }}
            >
              {v.fill_prompt || "(no prompt captured for this run)"}
            </pre>
          </div>

          <div style={{ border: "1px solid #e6ecf7", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "#f7f9fd", borderBottom: "1px solid #e6ecf7" }}>
              <span style={{ fontWeight: 800, fontSize: 13 }}>
                {modelReference ? "Reference image sent to the model" : "No image reference sent (text-to-image)"}
              </span>
              {modelReference && (
                <a href={modelReference} download style={{ fontSize: 12, fontWeight: 800, color: "#00a3e0", textDecoration: "none" }}>
                  download ↓
                </a>
              )}
            </div>
            <div style={{ padding: 12, background: "repeating-conic-gradient(#f4f6fb 0% 25%, #fff 0% 50%) 0 0/22px 22px" }}>
              {modelReference ? (
                <img
                  src={modelReference}
                  alt="wireframe reference"
                  title="click to zoom"
                  {...zoomProps(modelReference, "wireframe reference")}
                  style={{ width: "100%", display: "block", borderRadius: 10, border: "1px solid #e6ecf7", cursor: "zoom-in" }}
                />
              ) : (
                <div style={{ opacity: 0.55, fontSize: 12, padding: 12 }}>This background was generated from a text-only prompt; no image was sent.</div>
              )}
              <div style={{ fontSize: 11.5, opacity: 0.65, marginTop: 8 }}>
                {modelReference
                  ? "This transparent reference includes the final text, assets, and shapes with their actual colours and placements."
                  : "This transparent layout is shown for replay only; it was not sent to the text-to-image model."} Canvas {(v.brief?.ratio || job?.ratio || "1:1")}.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
