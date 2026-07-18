import { JSX } from "preact";
import { useRef, useState } from "preact/hooks";

import { Mode, overlap_violations } from "./core/formations";
import {
  ATTACK_LINE,
  COURT_HALF_LENGTH,
  COURT_WIDTH,
  serve_xy,
} from "./core/rotation";
import { SystemSpec, system_ids, SYSTEMS } from "./core/systems";
import { deserialize_system, serialize_system } from "./core/user_systems";
import {
  EditorState,
  X_MAX,
  X_MIN,
  Y_MAX,
  Y_MIN,
  actingSetterSlot,
  buildSpec,
  canSave,
  clampCoord,
  commitMove,
  copyKey,
  createEditorState,
  replaceOrAppend,
  roleHint,
  saveHint,
} from "./systemEditorState";

/** Full-screen, touch-first playing-system editor: the tablet port of
 * ui/system_editor.py. Drag the six tokens per situation/rotation, save
 * the working state as a custom system into the SAME stored list the
 * Import flow feeds. Drawn in CourtSurface.tsx's visual language (flat
 * colours, metre-unit strokes, kebab-case SVG attributes, chunky net). */

const FREE_ZONE_COLOR = "#2a6f97";
const COURT_COLOR = "#e8853b";
const FRONT_ZONE_COLOR = "#d9702a";
const NET_COLOR = "#222222";
const LINE_WIDTH = 0.075;
const NET_WIDTH = 0.175;
const TOKEN_RADIUS = 0.75;
const SETTER_FILL = "#1565c0";
const TEAM_FILL = "#2e7d32";
const OVERLAP_RING = "#e53935";

// viewBox: the left half plus the free zone, a hair past the net -- the
// exact clamp box, so a token can be dropped anywhere it is drawable.
const VB_X = X_MIN; // -13
const VB_Y = Y_MIN; // -2.5
const VB_W = (X_MAX - X_MIN) + 0.5; // 13.5
const VB_H = Y_MAX - Y_MIN; // 14

const _TAB_MODES: readonly Mode[] = [
  Mode.RECEIVE, Mode.SERVE_BASE, Mode.OFFENSE, Mode.DEFENSE,
];
const _TAB_LABELS = ["Receive", "Serve", "Offense", "Defense"];

interface DragState {
  slot: number;
  pointerId: number;
  x: number;
  y: number;
}

interface SystemEditorProps {
  userSystems: SystemSpec[];
  onCommitSystems: (nextList: SystemSpec[]) => void;
  onDropSystem: (systemId: string) => void;
  onClose: () => void;
}

export function SystemEditor({
  userSystems,
  onCommitSystems,
  onDropSystem,
  onClose,
}: SystemEditorProps) {
  const stateRef = useRef<EditorState>(createEditorState(system_ids()[0]));
  const [, bump] = useState(0);
  const [mode, setMode] = useState<Mode>(Mode.RECEIVE);
  const [key, setKey] = useState(0);
  const [copyFrom, setCopyFrom] = useState(0);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [status, setStatus] = useState<string>("");
  const svgRef = useRef<SVGSVGElement | null>(null);

  const state = stateRef.current;
  const rerender = () => bump((n) => n + 1);

  function loadBase(baseId: string): void {
    stateRef.current = createEditorState(baseId);
    setKey(0);
    setCopyFrom(0);
    setDrag(null);
    setStatus("");
    rerender();
  }

  function patch(fields: Partial<EditorState>): void {
    Object.assign(state, fields);
    rerender();
  }

  // --- token positions (with the live drag override) ---------------------
  const acting = actingSetterSlot(state, key);
  const chart = state.working[mode]![key];

  function slotPos(slot: number): [number, number] {
    if (mode === Mode.SERVE_BASE && slot === 0) {
      return serve_xy("left");
    }
    if (drag != null && drag.slot === slot) {
      return [drag.x, drag.y];
    }
    return chart[slot];
  }

  // --- live overlap feedback --------------------------------------------
  let violations: string[] = [];
  if (mode === Mode.RECEIVE || mode === Mode.SERVE_BASE) {
    const pos: Record<number, [number, number]> = {};
    for (let i = 0; i < 6; i += 1) {
      pos[i] = slotPos(i);
    }
    violations = overlap_violations(pos, "left", mode === Mode.SERVE_BASE ? [0] : []);
  }
  const warned = new Set<number>();
  for (let slot = 0; slot < 6; slot += 1) {
    if (violations.some((v) => v.includes(`P${slot + 1}`))) {
      warned.add(slot);
    }
  }

  // --- pointer -> viewBox metres, via the SVG's inverse screen CTM -------
  function toCourt(clientX: number, clientY: number): [number, number] {
    const svg = svgRef.current;
    if (svg == null) {
      return [0, 0];
    }
    const ctm = svg.getScreenCTM();
    if (ctm == null) {
      // Fallback: manual rect math (getScreenCTM can be null off-DOM).
      const rect = svg.getBoundingClientRect();
      return [
        VB_X + ((clientX - rect.left) / rect.width) * VB_W,
        VB_Y + ((clientY - rect.top) / rect.height) * VB_H,
      ];
    }
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return [local.x, local.y];
  }

  function onTokenDown(slot: number, event: JSX.TargetedPointerEvent<SVGGElement>): void {
    if (mode === Mode.SERVE_BASE && slot === 0) {
      return; // the server is pinned + never draggable
    }
    event.stopPropagation();
    (event.currentTarget as unknown as Element).setPointerCapture(event.pointerId);
    // Anchor the drag on the token's stored spot, not the touch point, so a
    // tap does not jump it; pointermove updates from the finger thereafter.
    const [bx, by] = chart[slot];
    setDrag({ slot, pointerId: event.pointerId, x: bx, y: by });
  }

  function onTokenMove(slot: number, event: JSX.TargetedPointerEvent<SVGGElement>): void {
    if (drag == null || drag.slot !== slot || drag.pointerId !== event.pointerId) {
      return;
    }
    const [x, y] = clampCoord(...toCourt(event.clientX, event.clientY));
    setDrag({ slot, pointerId: event.pointerId, x, y });
  }

  function onTokenUp(slot: number, event: JSX.TargetedPointerEvent<SVGGElement>): void {
    if (drag == null || drag.slot !== slot || drag.pointerId !== event.pointerId) {
      return;
    }
    try {
      (event.currentTarget as unknown as Element).releasePointerCapture(event.pointerId);
    } catch {
      // capture may already be gone; ignore
    }
    commitMove(state, mode, key, slot, drag.x, drag.y);
    setDrag(null);
    setStatus("");
    rerender();
  }

  // --- save / delete / revert -------------------------------------------
  const savable = canSave(state);
  const hint = saveHint(state);
  const sid = state.id.trim();
  const isStored = userSystems.some((s) => s.id === sid);

  function onSave(): void {
    if (!savable) {
      return;
    }
    let spec: SystemSpec;
    try {
      // Round-trip through the real validator so a save can never store a
      // system the app would later reject on load.
      spec = deserialize_system(serialize_system(buildSpec(state)));
    } catch (e) {
      setStatus((e as Error).message);
      return;
    }
    const nextList = replaceOrAppend(userSystems, spec);
    onCommitSystems(nextList);
    loadBase(spec.id); // reload from the (now merged) registry
    setStatus(`saved ${spec.id}`);
  }

  function onDelete(): void {
    if (!isStored) {
      return;
    }
    if (!window.confirm(`Delete the custom system '${sid}'?`)) {
      return;
    }
    onDropSystem(sid);
    loadBase(system_ids()[0]);
    setStatus(`deleted ${sid}`);
  }

  function onRevert(): void {
    loadBase(state.base_id);
  }

  return (
    <div className="overlay-backdrop">
      <div className="overlay-panel system-editor">
        <div className="system-editor-header">
          <label className="system-editor-field">
            Base system
            <select
              value={state.base_id}
              onChange={(e) => loadBase((e.currentTarget as HTMLSelectElement).value)}
            >
              {system_ids().map((id) => (
                <option key={id} value={id}>{SYSTEMS[id].label}</option>
              ))}
            </select>
          </label>
          <label className="system-editor-field id">
            id
            <input
              value={state.id}
              onInput={(e) => patch({ id: (e.currentTarget as HTMLInputElement).value })}
            />
          </label>
          <label className="system-editor-field grow">
            label
            <input
              value={state.label}
              onInput={(e) => patch({ label: (e.currentTarget as HTMLInputElement).value })}
            />
          </label>
          <label className="system-editor-field grow2">
            description
            <input
              value={state.description}
              onInput={(e) => patch({ description: (e.currentTarget as HTMLInputElement).value })}
            />
          </label>
          <label className="system-editor-field narrow">
            setters
            <input
              type="number"
              min="0"
              max="2"
              value={String(state.expected_setters)}
              onInput={(e) => {
                const raw = Number((e.currentTarget as HTMLInputElement).value);
                const clamped = Number.isFinite(raw) ? Math.min(Math.max(Math.round(raw), 0), 2) : 0;
                patch({ expected_setters: clamped });
              }}
            />
          </label>
          <div className="button-row compact system-editor-actions">
            <button type="button" className="primary" disabled={!savable} onClick={onSave}>
              Save
            </button>
            <button type="button" disabled={!isStored} onClick={onDelete}>
              Delete
            </button>
            <button type="button" onClick={onRevert}>
              Revert
            </button>
            <button type="button" className="ghost" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="system-editor-hintline">
          {hint !== "" ? <span className="system-editor-hint">{hint}</span> : null}
          {status !== "" ? <span className="system-editor-status">{status}</span> : null}
        </div>

        <div className="system-editor-tabs">
          <div className="system-editor-tabbar">
            {_TAB_MODES.map((m, i) => (
              <button
                key={m}
                type="button"
                className={mode === m ? "primary" : ""}
                onClick={() => { setMode(m); setDrag(null); }}
              >
                {_TAB_LABELS[i]}
              </button>
            ))}
          </div>

          {state.uses_setter_roles ? (
            <div className="system-editor-rotrow">
              {[0, 1, 2, 3, 4, 5].map((k) => (
                <button
                  key={k}
                  type="button"
                  className={key === k ? "primary" : ""}
                  onClick={() => {
                    setKey(k);
                    setCopyFrom([0, 1, 2, 3, 4, 5].find((j) => j !== k) ?? 0);
                    setDrag(null);
                  }}
                >
                  {`Setter at P${k + 1}`}
                </button>
              ))}
              <span className="system-editor-copy">
                <select
                  value={String(copyFrom)}
                  onChange={(e) => setCopyFrom(Number((e.currentTarget as HTMLSelectElement).value))}
                >
                  {[0, 1, 2, 3, 4, 5].filter((k) => k !== key).map((k) => (
                    <option key={k} value={String(k)}>{`Copy from P${k + 1}`}</option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => { copyKey(state, mode, copyFrom, key); setDrag(null); rerender(); }}
                >
                  Copy
                </button>
              </span>
            </div>
          ) : (
            <div className="system-editor-rotrow">
              <label className="system-editor-field">
                Setting slot
                <select
                  value={String(state.fixed_setter_slot)}
                  onChange={(e) => patch({ fixed_setter_slot: Number((e.currentTarget as HTMLSelectElement).value) })}
                >
                  {[0, 1, 2, 3, 4, 5].map((s) => (
                    <option key={s} value={String(s)}>{`P${s + 1}`}</option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </div>

        <div className="system-editor-court">
          <svg
            ref={svgRef}
            className="system-editor-svg"
            viewBox={`${VB_X} ${VB_Y} ${VB_W} ${VB_H}`}
            preserveAspectRatio="xMidYMid meet"
          >
            {/* free zone, court, front zone -- flat colours like the desktop */}
            <rect x={VB_X} y={VB_Y} width={VB_W} height={VB_H} fill={FREE_ZONE_COLOR} />
            <rect x={-COURT_HALF_LENGTH} y={0} width={COURT_HALF_LENGTH} height={COURT_WIDTH} fill={COURT_COLOR} />
            <rect x={-ATTACK_LINE} y={0} width={ATTACK_LINE} height={COURT_WIDTH} fill={FRONT_ZONE_COLOR} />

            {/* boundary + attack line */}
            <rect
              x={-COURT_HALF_LENGTH}
              y={0}
              width={COURT_HALF_LENGTH}
              height={COURT_WIDTH}
              fill="none"
              stroke="#ffffff"
              stroke-width={LINE_WIDTH}
            />
            <line x1={-ATTACK_LINE} y1={0} x2={-ATTACK_LINE} y2={COURT_WIDTH} stroke="#ffffff" stroke-width={LINE_WIDTH} />

            {/* chunky net at x = 0, over a dashed centre line */}
            <line x1={0} y1={-0.6} x2={0} y2={COURT_WIDTH + 0.6} stroke={NET_COLOR} stroke-width={NET_WIDTH} />
            <line x1={0} y1={0} x2={0} y2={COURT_WIDTH} stroke="#ffffff" stroke-width={0.05} stroke-dasharray="0.2 0.15" />

            {/* tokens */}
            {[0, 1, 2, 3, 4, 5].map((slot) => {
              const [x, y] = slotPos(slot);
              const ghost = mode === Mode.SERVE_BASE && slot === 0;
              const hintText = ghost ? "serves" : roleHint(state, key, slot);
              const fill = slot === acting ? SETTER_FILL : TEAM_FILL;
              return (
                <g
                  key={slot}
                  transform={`translate(${x} ${y})`}
                  className="system-editor-token"
                  style={{ opacity: ghost ? 0.4 : 1, cursor: ghost ? "default" : "grab" }}
                  onPointerDown={(e) => onTokenDown(slot, e)}
                  onPointerMove={(e) => onTokenMove(slot, e)}
                  onPointerUp={(e) => onTokenUp(slot, e)}
                  onPointerCancel={() => setDrag(null)}
                >
                  {warned.has(slot) ? (
                    <circle cx={0} cy={0} r={TOKEN_RADIUS + 0.18} fill="none" stroke={OVERLAP_RING} stroke-width={0.13} />
                  ) : null}
                  <circle cx={0} cy={0} r={TOKEN_RADIUS} fill={fill} stroke="#ffffff" stroke-width={0.06} />
                  <text x={0} y={0.2} className="system-editor-token-label" text-anchor="middle">
                    {`P${slot + 1}`}
                  </text>
                  {hintText !== "" ? (
                    <text x={0} y={TOKEN_RADIUS + 0.5} className="system-editor-token-hint" text-anchor="middle">
                      {hintText}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </svg>
        </div>

        <div className="system-editor-warnline">
          {violations.length > 0 ? (
            <span className="system-editor-warn">{`⚠ ${violations.join("; ")}`}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
