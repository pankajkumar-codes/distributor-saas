import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/fraunces/wght.css";
import "@fontsource-variable/hanken-grotesk/wght.css";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
