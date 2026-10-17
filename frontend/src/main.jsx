import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import BrandsPage from "./pages/BrandsPage";
import BrandHomePage from "./pages/BrandHomePage";
import CreatePage from "./pages/CreatePage";
import JobPage from "./pages/JobPage";
import EditPage from "./pages/EditPage";
import JobsPage from "./pages/JobsPage";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <BrowserRouter>
    <App>
      <Routes>
        <Route path="/" element={<BrandsPage />} />
        <Route path="/b/:brandId" element={<BrandHomePage />} />
        <Route path="/b/:brandId/jobs" element={<JobsPage />} />
        <Route path="/b/:brandId/new" element={<CreatePage />} />
        <Route path="/b/:brandId/j/:jobId" element={<JobPage />} />
        <Route path="/b/:brandId/j/:jobId/e/:editId" element={<EditPage />} />
      </Routes>
    </App>
  </BrowserRouter>
);
