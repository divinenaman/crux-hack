import React, { useEffect, useState } from "react";
import { closeZoom, onZoomChange } from "../lib/zoom";

export default function Lightbox() {
  const [box, setBox] = useState(null);

  useEffect(() => onZoomChange(setBox), []);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && closeZoom();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!box) return null;
  return (
    <div
      onClick={closeZoom}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(6,12,28,0.88)",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        cursor: "zoom-out",
        padding: 24,
      }}
    >
      <img
        src={box.url}
        alt={box.caption || "zoom"}
        style={{ maxWidth: "94vw", maxHeight: "86vh", objectFit: "contain", borderRadius: 10, background: "#fff" }}
      />
      <div style={{ color: "#dbe4ff", fontSize: 13, fontWeight: 600, display: "flex", gap: 14, alignItems: "center" }}>
        <span>{box.caption}</span>
        <span style={{ opacity: 0.55 }}>click anywhere or Esc to close</span>
      </div>
    </div>
  );
}
