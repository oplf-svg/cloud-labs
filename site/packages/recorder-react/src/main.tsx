import { createRoot, type Root } from "react-dom/client";
import { readData } from "@recorder/core";
import { Recorder } from "./Recorder.tsx";

class RecorderReact extends HTMLElement {
  #root: Root | undefined;

  connectedCallback() {
    this.#root = createRoot(this);
    this.#root.render(<Recorder {...readData(this)} />);
  }

  disconnectedCallback() {
    this.#root?.unmount();
    this.#root = undefined;
  }
}

customElements.define("recorder-react", RecorderReact);
