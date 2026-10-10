// Explicit development-only preview; not a production entry point.
import { createRoot } from "react-dom/client";
import App, { Boundary } from "./App";
import fixture from "./preview-fixture.json";
import type { Scan } from "./bridge";
import "./style.css";
createRoot(document.getElementById("root")!).render(
  <Boundary>
    <App initialScan={fixture as Scan} preview />
  </Boundary>,
);
