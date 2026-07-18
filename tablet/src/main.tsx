import { render } from "preact";

import { App } from "./App";
import { loadUserSystems } from "./browserStorage";
import { refresh_registry } from "./core/user_systems";
import "./app.css";

// Register imported custom systems into SYSTEMS before the first render,
// so they survive reloads and are selectable everywhere immediately.
refresh_registry(loadUserSystems());

render(<App />, document.getElementById("app")!);
