import React, { useEffect, useRef, useState } from "react";
import { Stage, Layer, Image as KImage, Text, Rect, Ellipse, Group, Label, Tag } from "react-konva";
import { fileUrl } from "../lib/fileUrl";
import { openZoom } from "../lib/zoom";
import JudgeDiffPanel from "./JudgeDiffPanel";
import TrailPanel from "./TrailPanel";

const TYPE_COLOR = { text: "#6366f1", image: "#0ea5e9", shape: "#f59e0b", raster: "#0b1a3a" };

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
  const [hover, setHover] = useState(-1);
  const [scale, setScale] = useState(0.55);
  const [mode, setMode] = useState("composite");
  const [sideTab, setSideTab] = useState("layers");
  const stageRef = useRef();
  const wrapRef = useRef(null);
  const design = layers.find((l) => l.role === "design" || l.role === "background");
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
    if (next != null) update(sel, { content: next, style: { ...(layer.style || {}), lines: undefined } });
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
            {design?.src && <button style={btn(false)} onClick={() => openZoom(fileUrl(design.src), "design raster")}>Zoom</button>}
            <button style={btn(false)} onClick={exportPNG}>Export PNG</button>
          </div>
        </div>
        <Stage ref={stageRef} width={W * scale} height={H * scale} scaleX={scale} scaleY={scale} onMouseDown={(e) => { if (e.target === e.target.getStage()) setSel(-1); }}>
          <Layer>
            {mode !== "layers" && designImg ? <KImage image={designImg} width={W} height={H} opacity={mode === "ghost" ? 0.35 : 1} /> : <Rect width={W} height={H} fill="#ffffff" />}
            {layers.map((l, i) => {
              if (i === 0) return null;
              if (l.visible === false) return null;
              const [x, y, w, h] = l.bbox;
              const active = i === sel;
              const hovered = i === hover;
              const showBox = active || hovered || mode === "layers";
              const baked = l.baked && l.type === "text";
              if (l.type === "image") {
                return (
                  <React.Fragment key={i}>
                    <LayerImage layer={l} x={x} y={y} w={w} h={h} active={active} onSelect={() => setSel(i)} onChange={(p) => update(i, { bbox: p })} />
                    {showBox && <RoleBox x={x} y={y} w={w} h={h} role={l.role} color={TYPE_COLOR[l.type]} dashed={!active} />}
                  </React.Fragment>
                );
              }
              if (l.type === "shape") {
                return (
                  <React.Fragment key={i}>
                    <LayerShape layer={l} x={x} y={y} w={w} h={h} active={active} onSelect={() => setSel(i)} onChange={(p) => update(i, { bbox: p })} />
                    {showBox && <RoleBox x={x} y={y} w={w} h={h} role={l.role} color={TYPE_COLOR[l.type]} dashed={!active} />}
                  </React.Fragment>
                );
              }
              return (
                <Group key={i} x={x} y={y} draggable={!l.locked && !baked} onDragEnd={(e) => update(i, { bbox: [e.target.x(), e.target.y(), w, h] })} onClick={() => setSel(i)} onTap={() => setSel(i)} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(-1)}>
                  {(active || hovered) && <Rect width={w} height={h} stroke="#00a3e0" dash={[6, 4]} strokeWidth={2} />}
                  {!baked && l.role === "cta" && l.style?.draw_bg !== false && <Rect width={w} height={h} fill="#0b1a3a" cornerRadius={h / 2} />}
                  {!baked && (
                    <Text
                      text={(l.style?.lines?.length ? l.style.lines : String(l.content || "").split("\n")).join("\n")}
                      width={w}
                      height={h}
                      wrap={l.style?.lines?.length ? "none" : "word"}
                      verticalAlign="middle"
                      padding={l.style?.padding ?? 0}
                      lineHeight={l.style?.lineGap || l.style?.lineHeight || 1.15}
                      fill={l.style?.color || (l.role === "cta" ? "#ffffff" : "#000856")}
                      fontStyle={String(l.style?.weight || 400) >= 700 ? "bold" : "normal"}
                      fontFamily={`${l.style?.font || "Figtree"}, ${l.style?.fallback || "sans-serif"}`}
                      fontSize={l.style?.size || 24}
                      align={l.style?.align || (l.role === "cta" ? "center" : "left")}
                    />
                  )}
                  {(showBox || mode === "layers") && <RoleBox x={0} y={0} w={w} h={h} role={l.role + (baked ? " · baked" : "")} color={TYPE_COLOR[l.type]} dashed={!active} local />}
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
            {manifest?.pending_layers && (
              <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8, padding: "6px 10px", fontSize: 11, marginBottom: 8 }}>
                ⚡ layers assembling — background + pieces land shortly
              </div>
            )}
            {layers.map((l, i) => (
              <div
                key={i}
                onClick={() => setSel(i)}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(-1)}
                style={{ padding: "8px 10px", borderRadius: 10, marginBottom: 6, cursor: "pointer", background: sel === i ? "#e8efff" : hover === i ? "#f0f7ff" : "#f7f9fd", border: sel === i ? "1px solid #93c5fd" : "1px solid #e6ecf7" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: 13 }}>
                  <span style={{ background: TYPE_COLOR[l.type] || "#94a3b8", color: "#fff", borderRadius: 4, padding: "1px 6px", fontSize: 10, letterSpacing: 0.4 }}>{l.type}</span>
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.role}{l.locked ? " 🔒" : ""}{l.baked ? " · baked" : ""}</span>
                  <span
                    onClick={(e) => { e.stopPropagation(); update(i, { visible: l.visible === false }); }}
                    title={l.visible === false ? "show layer" : "hide layer"}
                    style={{ opacity: l.visible === false ? 0.3 : 0.8, fontSize: 13 }}
                  >
                    {l.visible === false ? "🚫" : "👁"}
                  </span>
                </div>
                <div style={{ fontSize: 10, opacity: 0.5, marginTop: 2 }}>
                  box [{Math.round(l.bbox[0])}, {Math.round(l.bbox[1])}, {Math.round(l.bbox[2])}×{Math.round(l.bbox[3])}]
                  {l.style?.placed_by ? ` · ${l.style.placed_by}` : ""}
                </div>
                <div style={{ fontSize: 11, opacity: 0.65, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {(l.content || l.asset_id || l.src || "").slice(0, 42)}
                </div>
                {sel === i && l.type === "text" && !l.baked && (
                  <textarea value={l.content} onChange={(e) => update(i, { content: e.target.value, style: { ...(l.style || {}), lines: undefined } })} rows={3} style={{ width: "100%", marginTop: 6, font: "inherit", borderRadius: 6, border: "1px solid #dfe5f1", padding: 6 }} />
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
  const rot = Number(layer.style?.rotation) || 0; // degrees clockwise, centre-pivoted
  return (
    <Group x={x} y={y} draggable={!layer.locked} onClick={onSelect} onTap={onSelect} onDragEnd={(e) => onChange([e.target.x(), e.target.y(), w, h])}>
      {active && <Rect width={w} height={h} stroke="#00a3e0" dash={[6, 4]} strokeWidth={2} />}
      {img ? <KImage image={img} width={w} height={h} x={w / 2} y={h / 2} offsetX={w / 2} offsetY={h / 2} rotation={rot} /> : <Rect width={w} height={h} fill="#dfe5f1" />}
    </Group>
  );
}

function LayerShape({ layer, x, y, w, h, active, onSelect, onChange }) {
  const st = layer.style || {};
  const shape = String(st.shape || "rect").toLowerCase();
  const fill = st.fill || "#0b1a3a";
  const stroke = st.stroke || undefined;
  const strokeWidth = st.strokeWidth || 0;
  const rot = Number(st.rotation) || 0; // degrees clockwise, centre-pivoted
  const common = { fill, stroke, strokeWidth, width: w, height: h };
  return (
    <Group x={x} y={y} draggable={!layer.locked} onClick={onSelect} onTap={onSelect} onDragEnd={(e) => onChange([e.target.x(), e.target.y(), w, h])}>
      {active && <Rect width={w} height={h} stroke="#00a3e0" dash={[6, 4]} strokeWidth={2} />}
      {shape === "circle" ? (
        <Ellipse {...common} radiusX={w / 2} radiusY={h / 2} x={w / 2} y={h / 2} rotation={rot} listening={false} />
      ) : (
        <Rect {...common} x={w / 2} y={h / 2} offsetX={w / 2} offsetY={h / 2} rotation={rot} cornerRadius={shape === "pill" ? h / 2 : st.radius || 0} listening={false} />
      )}
    </Group>
  );
}

function RoleBox({ x, y, w, h, role, color, dashed, local }) {
  return (
    <Group x={x} y={y}>
      <Rect width={w} height={h} stroke={color} strokeWidth={1.5} dash={dashed ? [5, 4] : undefined} listening={false} />
      <Label x={0} y={-22} listening={false}>
        <Tag fill={color} cornerRadius={4} />
        <Text text={` ${role} `} fontSize={12} fill="#fff" padding={2} fontStyle="bold" />
      </Label>
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
