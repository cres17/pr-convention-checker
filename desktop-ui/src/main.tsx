import { createRoot } from "react-dom/client";
import App, { Boundary } from "./App";
import "./style.css";
createRoot(document.getElementById("root")!).render(
  <Boundary>
    <App />
  </Boundary>,
);
