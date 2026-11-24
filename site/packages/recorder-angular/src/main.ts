import { provideZonelessChangeDetection } from "@angular/core";
import { createCustomElement } from "@angular/elements";
import { createApplication } from "@angular/platform-browser";
import { Recorder } from "./recorder.ts";

const { injector } = await createApplication({ providers: [provideZonelessChangeDetection()] });
customElements.define("recorder-angular", createCustomElement(Recorder, { injector }));
