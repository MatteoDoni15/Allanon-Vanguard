import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import App from "./App.jsx";
import GeneratePage from "./pages/GeneratePage.jsx";
import BlogPage from "./pages/BlogPage.jsx";
import PoliciesPage from "./pages/PoliciesPage.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<GeneratePage />} />
          {/* Matched before the catch-all :slug below so it isn't parsed as a blog id. */}
          <Route path="policies" element={<PoliciesPage />} />
          {/* Public URL the user asked for: /blog_1, /blog_2, ... .
              React Router can't bind a partial segment (blog_:id), so we match
              the whole segment and parse the number inside BlogPage. */}
          <Route path=":slug" element={<BlogPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
