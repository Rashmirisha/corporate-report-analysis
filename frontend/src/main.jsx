import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

// <App /> mounts its own <BrowserRouter> so the shell can be tested
// without forcing router context on every test. <StrictMode> lives here
// so it wraps the whole tree including the router.
createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
