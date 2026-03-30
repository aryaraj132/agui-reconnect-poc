// Prevent "already defined" errors for custom elements during HMR
const origDefine = customElements.define.bind(customElements);
customElements.define = (name: string, ctor: CustomElementConstructor, options?: ElementDefinitionOptions) => {
  if (!customElements.get(name)) origDefine(name, ctor, options);
};

import { createRoot } from "react-dom/client";
import App from "./App";
import "./globals.css";

const root = createRoot(document.getElementById("root")!);
root.render(<App />);
