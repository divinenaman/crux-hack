import React from "react";
import { Link, useParams } from "react-router-dom";
import Lightbox from "./components/Lightbox";

export default function App({ children }) {
  const { brandId, jobId, editId } = useParams();
  return (
    <div style={{ display: "grid", gridTemplateRows: "auto 1fr", height: "100%" }}>
      <Lightbox />
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 16px",
          background: "#fff",
          borderBottom: "1px solid #dfe5f1",
        }}
      >
        <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
          <Link to="/" style={{ fontWeight: 800, fontSize: 18, color: "#0b1a3a", textDecoration: "none" }}>
            Crux — Agentic Image Editor
          </Link>
          {brandId && (
            <span style={{ fontSize: 13 }}>
              / <Link to={`/b/${brandId}`} style={{ color: "#00a3e0", fontWeight: 700 }}>{brandId}</Link>
            </span>
          )}
          {jobId && (
            <span style={{ fontSize: 13, opacity: 0.7 }}>
              / <Link to={`/b/${brandId}/j/${jobId}`} style={{ color: "#00a3e0" }}>job</Link>
            </span>
          )}
          {editId && <span style={{ fontSize: 13, opacity: 0.7 }}>/ {editId}</span>}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {brandId && (
            <>
              <a href={`/b/${brandId}`} style={tabBtn}>assets</a>
              <a href={`/b/${brandId}/jobs`} style={tabBtn}>jobs</a>
              <a href={`/b/${brandId}/new`} style={tabBtn}>create</a>
            </>
          )}
        </div>
      </header>
      <main style={{ minHeight: 0, overflow: "auto" }}>{children}</main>
    </div>
  );
}

const tabBtn = {
  border: "1px solid #dfe5f1",
  borderRadius: 8,
  padding: "6px 12px",
  cursor: "pointer",
  fontWeight: 600,
  color: "#0b1a3a",
  textDecoration: "none",
  fontSize: 13,
};
