import React, { useEffect, useRef, useState } from "react";
import { Stage, Layer, Image as KImage, Text, Rect, Group } from "react-konva";
import { fileUrl } from "../lib/fileUrl";
import JudgeDiffPanel from "./JudgeDiffPanel";
import TrailPanel from "./TrailPanel";

function useImage(src) {
  const [img, setImg] = useState(null);
  useEffect(() => {
    if (!src) return setImg(null);
    const i = new window.Image();
    i.crossOrigin = "anonymous";
    i.onload = () => setImg(i);
    i.onerror = () => setImg(null);
    i.src = src;
  }, [src]);
  return img;
}

export default function CanvasEditor({ job, manifest, variantId }) {
  const [layers, setLayers] = useState([]);
  const [sel, setSel] = useState(-1);
  const [scale, setScale] = useState(0.55);
  const [mode, setMode] = useState("composite");
  const [sideTab, setSideTab] = useState("diff");
  const stageRef = useRef();
  const wrapRef = useRef(null);
  const design = layers.find((l) => l.role === "design");
  const designImg = useImage(fileUrl(design?.src));
  const W = manifest?.canvas?.w || 1024;
  const H = manifest?.canvas?.h || 1024;
  const variant = (job?.variants || []).find((v) => v.id === (variantId || job?.selected)) || job?.variants?.[0];

  useEffect(() => {
    setLayers(manifest?.layers || []);
    setSel(-1);
  }, [manifest]);

  useEffect(() => {
    const srcs = new Set();
    (manifest?.layers || []).forEach((l) => l.style?.font_src && srcs.add(l.style.font_src));
    srcs.forEach((src) => {
      const name = String(src).split("/").pop().replace(/\.[^.]+$/, "");
      try {
        const ff = new FontFace(name, `url(${src})`);
        ff.load().then((f) => document.fonts.add(f)).catch(() => {});
      } catch {
        /* font unavailable — CSS fallback applies */
      }
    });
  }, [manifest]);

  useEffect(() => {
    const fit = () => {
      const el = wrapRef.current;
      if (!el) return;
      setScale(Math.min((el.clientWidth - 60) / W, (el.clientHeight - 60) / H, 1) || 0.55);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [W, H, manifest]);

  if (!manifest) {
    return <div style={{ opacity: 0.55, padding: 40, textAlign: "center" }}>Select a variant to open the editable canvas.</div>;
  }

  const update = (i, patch) => setLayers((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));

  const exportPNG = () => {
    const uri = stageRef.current.toDataURL({ pixelRatio: 2 });
    const a = document.createElement("a");
    a.href = uri;
    a.download = `${variantId || "design"}.png`;
    a.click();
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ ...manifest, layers }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${job?.id || "design"}_manifest.json`;
    a.click();
  };

  const editContent = () => {
    const layer = layers.find((l, i) => i === sel && l.type === "text");
    if (!layer) return;
    const next = window.prompt("Edit text", layer.content);
    if (next != null) update(sel, { content: next });
  };

  const failCount = (variant?.best_report?.items || []).filter((i) => !i.pass).length;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 16, height: "100%", minHeight: 0 }}>
      <div ref={wrapRef} style={{ background: "#e9edf6", borderRadius: 16, padding: 16, overflow: "auto", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", alignSelf: "stretch", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 6 }}>
            {["composite", "ghost", "layers"].map((m) => (
              <button key={m} onClick={() => setMode(m)} style={btn(mode === m)}>{m}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button style={btn(false)} onClick={() => setScale((s) => Math.max(0.2, s - 0.1))}>−</button>
            <button style={btn(false)} onClick={() => setScale((s) => Math.min(1.5, s + 0.1))}>+</button>
            <button style={btn(false)} onClick={exportPNG}>Export PNG</button>
          </div>
        </div>
        <Stage ref={stageRef} width={W * scale} height={H * scale} scaleX={scale} scaleY={scale} onMouseDown={(e) => { if (e.target === e.target.getStage()) setSel(-1); }}>
          <Layer>
            {mode !== "layers" && designImg ? <KImage image={designImg} width={W} height={H} opacity={mode === "ghost" ? 0.35 : 1} /> : <Rect width={W} height={H} fill="#ffffff" />}
            {layers.map((l, i) => {
              if (i === 0) return null;
              const [x, y, w, h] = l.bbox;
              const active = i === sel;
              if (l.type === "image") {
                return <LayerImage key={i} layer={l} x={x} y={y} w={w} h={h} active={active} onSelect={() => setSel(i)} onChange={(p) => update(i, { bbox: p })} />;
              }
              return (
                <Group key={i} x={x} y={y} draggable={!l.locked} onDragEnd={(e) => update(i, { bbox: [e.target.x(), e.target.y(), w, h] })} onClick={() => setSel(i)} onTap={() => setSel(i)}>
                  {active && <Rect width={w} height={h} stroke="#00a3e0" dash={[6, 4]} strokeWidth={2} />}
                  {l.role === "cta" && l.style?.draw_bg !== false && <Rect width={w} height={h} fill="#0b1a3a" cornerRadius={h / 2} />}
                  <Text
                    text={l.content}
                    width={w}
                    height={h}
                    padding={l.style?.padding ?? (l.role === "cta" ? h * 0.22 : 6)}
                    lineHeight={l.style?.lineHeight ?? 1.2}
                    fill={l.style?.color || (l.role === "cta" ? "#ffffff" : "#000856")}
                    fontStyle={String(l.style?.weight || 400) >= 700 ? "bold" : "normal"}
                    fontFamily={`${l.style?.font || "Figtree"}, ${l.style?.fallback || "sans-serif"}`}
                    fontSize={l.style?.size || 24}
                    align={l.style?.align || (l.role === "cta" ? "center" : "left")}
                  />
                </Group>
              );
            })}
          </Layer>
        </Stage>
      </div>

      <aside style={{ background: "#fff", borderRadius: 16, padding: 14, overflow: "auto", border: "1px solid #dfe5f1", display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 6 }}>
          {["layers", "diff", "trail"].map((t) => (
            <button
              key={t}
              onClick={() => setSideTab(t)}
              style={{ ...btn(sideTab === t), flex: 1, textTransform: "capitalize" }}
            >
              {t === "diff" ? `diff${failCount ? ` (${failCount})` : ""}` : t}
            </button>
          ))}
        </div>

        {sideTab === "layers" && (
          <div>
            {layers.map((l, i) => (
              <div key={i} onClick={() => setSel(i)} style={{ padding: "8px 10px", borderRadius: 10, marginBottom: 6, cursor: "pointer", background: sel === i ? "#e8efff" : "#f7f9fd", border: "1px solid #e6ecf7" }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{l.type} · {l.role}{l.locked ? " 🔒" : ""}</div>
                <div style={{ fontSize: 11, opacity: 0.65, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {(l.content || l.asset_id || l.src || "").slice(0, 42)}
                </div>
                {sel === i && l.type === "text" && (
                  <textarea value={l.content} onChange={(e) => update(i, { content: e.target.value })} rows={3} style={{ width: "100%", marginTop: 6, font: "inherit", borderRadius: 6, border: "1px solid #dfe5f1", padding: 6 }} />
                )}
              </div>
            ))}
            <button onClick={editContent} style={{ ...btn(false), width: "100%", background: "#00a3e0", color: "#fff", border: "none", marginTop: 6 }}>Edit selected text</button>
            <button onClick={exportJson} style={{ ...btn(false), width: "100%", marginTop: 8 }}>Export manifest</button>
          </div>
        )}

        {sideTab === "diff" && <JudgeDiffPanel variant={variant} brief={variant?.brief} />}

        {sideTab === "trail" && <TrailPanel job={job} />}
      </aside>
    </div>
  );
}

function LayerImage({ layer, x, y, w, h, active, onSelect, onChange }) {
  const img = useImage(fileUrl(layer.src));
  return (
    <Group x={x} y={y} draggable={!layer.locked} onClick={onSelect} onTap={onSelect} onDragEnd={(e) => onChange([e.target.x(), e.target.y(), w, h])}>
      {active && <Rect width={w} height={h} stroke="#00a3e0" dash={[6, 4]} strokeWidth={2} />}
      {img ? <KImage image={img} width={w} height={h} /> : <Rect width={w} height={h} fill="#dfe5f1" />}
    </Group>
  );
}

const btn = (active) => ({
  border: "1px solid #dfe5f1",
  background: active ? "#0b1a3a" : "#fff",
  color: active ? "#fff" : "#0b1a3a",
  borderRadius: 8,
  padding: "6px 10px",
  cursor: "pointer",
  fontWeight: 700,
  fontSize: 12,
});
