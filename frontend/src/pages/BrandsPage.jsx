import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

export default function BrandsPage() {
  const [brands, setBrands] = useState([]);
  const [id, setId] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    api.brands().then(setBrands).catch(() => setBrands([]));
  }, []);

  const create = async () => {
    const bid = id.trim().toLowerCase().replace(/\s+/g, "_");
    if (!bid) return;
    await api.createBrand(bid, id.trim());
    nav(`/b/${bid}`);
  };

  return (
    <div style={{ padding: 28, maxWidth: 860, margin: "0 auto" }}>
      <h2 style={{ margin: "0 0 6px" }}>Brands</h2>
      <p style={{ opacity: 0.65, fontSize: 13 }}>Each brand has its own asset classes (folders), rules, jobs and drafts.</p>
      <div style={{ display: "grid", gap: 10, marginTop: 18 }}>
        {brands.map((b) => (
          <Link
            key={b.id}
            to={`/b/${b.id}`}
            style={{
              display: "flex",
              justifyContent: "space-between",
              padding: "14px 16px",
              border: "1px solid #dfe5f1",
              borderRadius: 12,
              background: "#fff",
              textDecoration: "none",
              color: "#0b1a3a",
            }}
          >
            <b>{b.name || b.id}</b>
            <span style={{ opacity: 0.6, fontSize: 13 }}>{b.assets} assets · {b.jobs} jobs</span>
          </Link>
        ))}
        {!brands.length && <div style={{ opacity: 0.5 }}>No brands yet.</div>}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 22 }}>
        <input
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="new brand id (e.g. acme)"
          style={{ flex: 1, padding: "10px 12px", borderRadius: 10, border: "1px solid #dfe5f1", font: "inherit" }}
        />
        <button onClick={create} style={{ ...btn, background: "#0b1a3a", color: "#fff", border: "none" }}>
          Create brand
        </button>
      </div>
    </div>
  );
}

const btn = { borderRadius: 10, padding: "10px 16px", cursor: "pointer", fontWeight: 700, border: "1px solid #dfe5f1", background: "#fff" };
