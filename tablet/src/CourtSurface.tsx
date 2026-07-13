import { JSX } from "preact";
import { useRef } from "preact/hooks";

import {
  ATTACK_LINE,
  COURT_HALF_LENGTH,
  COURT_WIDTH,
  FREE_ZONE_X,
  FREE_ZONE_Y,
} from "./core/rotation";
import { CourtTokenSpec, CourtTrajectorySpec } from "./courtState";

/** Visual design mirrors the desktop app (ui/court_view.py + player_token.py):
 * flat colours, white 3px-equivalent lines, chunky dark net, open-wing
 * arrowheads, flat tokens. All strokes/fonts are in court metres so the
 * whole drawing scales as one piece (the desktop uses 40 px/metre; every
 * pixel width below is that value / 40). */

const MIN_X = -(COURT_HALF_LENGTH + FREE_ZONE_X);
const MIN_Y = -FREE_ZONE_Y;
const VIEWBOX_WIDTH = 2 * (COURT_HALF_LENGTH + FREE_ZONE_X);
const VIEWBOX_HEIGHT = COURT_WIDTH + 2 * FREE_ZONE_Y;
const TAP_THRESHOLD_PX = 12;

const FREE_ZONE_COLOR = "#2a6f97";
const COURT_COLOR = "#e8853b";
const FRONT_ZONE_COLOR = "#d9702a";
const NET_COLOR = "#222222";
const LINE_WIDTH = 0.075; // 3 px on the desktop court
const NET_WIDTH = 0.175; // 7 px
const ARROW_WIDTH = 0.1; // 4 px
const ARROW_HEAD = 0.4; // 16 px
const RUBBER_WIDTH = 0.075; // 3 px

const SERVE_ARROW = "#ffffff";
const ATTACK_ARROW = "#ffd600";

const TOKEN_RADIUS = 0.75; // 30 px disc, comfortable touch target
const SETTER_RING = "#ffd600";

interface CourtPoint {
  x: number;
  y: number;
}

interface CourtTrajectory {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface SvgViewTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
}

interface PointerDragState {
  pointerId: number;
  pressCourt: CourtPoint;
  pressClientX: number;
  pressClientY: number;
  transform: SvgViewTransform;
}

interface CourtSurfaceProps {
  leftTeamName: string;
  rightTeamName: string;
  tokens: CourtTokenSpec[];
  trajectories: CourtTrajectorySpec[];
  onPlayerTap: (teamKey: string, playerId: string) => void;
  onCourtTap: (x: number, y: number) => void;
  onTrajectory: (x1: number, y1: number, x2: number, y2: number) => void;
}

/** Open-wing arrow path like the desktop _Arrow: shaft plus two wings at
 * +-25 degrees drawn back from the tip (stroked, not filled). */
function arrowPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = x1 - x2;
  const dy = y1 - y2;
  const length = Math.hypot(dx, dy);
  let d = `M ${x1} ${y1} L ${x2} ${y2}`;
  if (length < 0.001) {
    return d;
  }
  const head = Math.min(ARROW_HEAD, length);
  const ux = dx / length;
  const uy = dy / length;
  for (const deg of [-25, 25]) {
    const a = (deg * Math.PI) / 180;
    const wx = x2 + (ux * Math.cos(a) - uy * Math.sin(a)) * head;
    const wy = y2 + (ux * Math.sin(a) + uy * Math.cos(a)) * head;
    d += ` M ${x2} ${y2} L ${wx} ${wy}`;
  }
  return d;
}

function measureSvg(svg: SVGSVGElement): SvgViewTransform {
  const rect = svg.getBoundingClientRect();
  const scale = Math.min(rect.width / VIEWBOX_WIDTH, rect.height / VIEWBOX_HEIGHT);
  const renderedWidth = VIEWBOX_WIDTH * scale;
  const renderedHeight = VIEWBOX_HEIGHT * scale;
  return {
    scale,
    offsetX: rect.left + (rect.width - renderedWidth) / 2,
    offsetY: rect.top + (rect.height - renderedHeight) / 2,
  };
}

function clientToCourt(transform: SvgViewTransform, clientX: number, clientY: number): CourtPoint {
  return {
    x: MIN_X + (clientX - transform.offsetX) / transform.scale,
    y: MIN_Y + (clientY - transform.offsetY) / transform.scale,
  };
}

function playerElementAt(clientX: number, clientY: number): Element | null {
  return document.elementFromPoint(clientX, clientY)?.closest("[data-player-id]") ?? null;
}

export function CourtSurface({
  leftTeamName,
  rightTeamName,
  tokens,
  trajectories,
  onPlayerTap,
  onCourtTap,
  onTrajectory,
}: CourtSurfaceProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const pointerRef = useRef<PointerDragState | null>(null);
  const draftRef = useRef<SVGPathElement | null>(null);
  const queuedDraftRef = useRef<CourtTrajectory | null>(null);
  const rafRef = useRef<number | null>(null);

  function paintDraftTrajectory(trajectory: CourtTrajectory | null): void {
    const path = draftRef.current;
    if (path == null) {
      return;
    }
    if (trajectory == null) {
      path.style.display = "none";
      return;
    }
    path.style.display = "block";
    path.setAttribute(
      "d",
      arrowPath(trajectory.x1, trajectory.y1, trajectory.x2, trajectory.y2),
    );
  }

  function flushDraftTrajectory(): void {
    rafRef.current = null;
    paintDraftTrajectory(queuedDraftRef.current);
  }

  function scheduleDraftTrajectory(trajectory: CourtTrajectory | null): void {
    queuedDraftRef.current = trajectory;
    if (rafRef.current != null) {
      return;
    }
    rafRef.current = window.requestAnimationFrame(flushDraftTrajectory);
  }

  function clearPointerState(): void {
    pointerRef.current = null;
    queuedDraftRef.current = null;
    if (rafRef.current != null) {
      window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    paintDraftTrajectory(null);
  }

  function handlePointerDown(event: JSX.TargetedPointerEvent<SVGSVGElement>): void {
    if (event.button !== 0 || svgRef.current == null) {
      return;
    }
    const svg = svgRef.current;
    const transform = measureSvg(svg);
    const pressCourt = clientToCourt(transform, event.clientX, event.clientY);
    pointerRef.current = {
      pointerId: event.pointerId,
      pressCourt,
      pressClientX: event.clientX,
      pressClientY: event.clientY,
      transform,
    };
    svg.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: JSX.TargetedPointerEvent<SVGSVGElement>): void {
    if (svgRef.current == null || pointerRef.current?.pointerId !== event.pointerId) {
      return;
    }
    const dx = event.clientX - pointerRef.current.pressClientX;
    const dy = event.clientY - pointerRef.current.pressClientY;
    if (Math.hypot(dx, dy) <= TAP_THRESHOLD_PX) {
      scheduleDraftTrajectory(null);
      return;
    }
    const current = clientToCourt(pointerRef.current.transform, event.clientX, event.clientY);
    scheduleDraftTrajectory({
      x1: pointerRef.current.pressCourt.x,
      y1: pointerRef.current.pressCourt.y,
      x2: current.x,
      y2: current.y,
    });
  }

  function handlePointerUp(event: JSX.TargetedPointerEvent<SVGSVGElement>): void {
    const pointer = pointerRef.current;
    if (svgRef.current == null || pointer == null || pointer.pointerId !== event.pointerId) {
      clearPointerState();
      return;
    }
    svgRef.current.releasePointerCapture(event.pointerId);
    const releaseCourt = clientToCourt(pointer.transform, event.clientX, event.clientY);
    const distance = Math.hypot(event.clientX - pointer.pressClientX, event.clientY - pointer.pressClientY);
    clearPointerState();

    if (distance > TAP_THRESHOLD_PX) {
      onTrajectory(pointer.pressCourt.x, pointer.pressCourt.y, releaseCourt.x, releaseCourt.y);
      return;
    }

    const playerElement = playerElementAt(event.clientX, event.clientY);
    const teamKey = playerElement?.getAttribute("data-team-key");
    const playerId = playerElement?.getAttribute("data-player-id");
    if (teamKey != null && playerId != null) {
      onPlayerTap(teamKey, playerId);
    } else {
      onCourtTap(releaseCourt.x, releaseCourt.y);
    }
  }

  function handlePointerCancel(): void {
    clearPointerState();
  }

  return (
    <div className="court-surface">
      <svg
        ref={svgRef}
        className="court-svg"
        viewBox={`${MIN_X} ${MIN_Y} ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
      >
        {/* playing surface: flat colours exactly like the desktop court */}
        <rect x={MIN_X} y={MIN_Y} width={VIEWBOX_WIDTH} height={VIEWBOX_HEIGHT} fill={FREE_ZONE_COLOR} />
        <rect x={-COURT_HALF_LENGTH} y={0} width={COURT_HALF_LENGTH * 2} height={COURT_WIDTH} fill={COURT_COLOR} />
        <rect x={-ATTACK_LINE} y={0} width={ATTACK_LINE * 2} height={COURT_WIDTH} fill={FRONT_ZONE_COLOR} />

        {/* boundary + attack lines */}
        <rect
          x={-COURT_HALF_LENGTH}
          y={0}
          width={COURT_HALF_LENGTH * 2}
          height={COURT_WIDTH}
          fill="none"
          stroke="#ffffff"
          stroke-width={LINE_WIDTH}
        />
        <line x1={-ATTACK_LINE} y1={0} x2={-ATTACK_LINE} y2={COURT_WIDTH} stroke="#ffffff" stroke-width={LINE_WIDTH} />
        <line x1={ATTACK_LINE} y1={0} x2={ATTACK_LINE} y2={COURT_WIDTH} stroke="#ffffff" stroke-width={LINE_WIDTH} />

        {/* net (thick, past the sidelines) over a dashed centre line */}
        <line x1={0} y1={-0.6} x2={0} y2={COURT_WIDTH + 0.6} stroke={NET_COLOR} stroke-width={NET_WIDTH} />
        <line
          x1={0}
          y1={0}
          x2={0}
          y2={COURT_WIDTH}
          stroke="#ffffff"
          stroke-width={0.05}
          stroke-dasharray="0.2 0.15"
        />

        {/* team names in the free zone corners */}
        <text className="court-side-label" x={-COURT_HALF_LENGTH + 0.15} y={-0.85}>
          {leftTeamName}
        </text>
        <text className="court-side-label" x={COURT_HALF_LENGTH - 0.15} y={-0.85} text-anchor="end">
          {rightTeamName}
        </text>

        {/* recorded trajectories, newest fully opaque, older ones faded */}
        {trajectories.map(({ kind, trajectory, opacity }, index) => {
          const [x1, y1, x2, y2] = trajectory;
          return (
            <path
              key={`${kind}-${index}-${trajectory.join("-")}`}
              d={arrowPath(x1, y1, x2, y2)}
              fill="none"
              stroke={kind === "serve" ? SERVE_ARROW : ATTACK_ARROW}
              stroke-width={ARROW_WIDTH}
              stroke-linecap="round"
              stroke-linejoin="round"
              opacity={opacity}
            />
          );
        })}

        {/* rubber-band arrow while drawing */}
        <path
          ref={draftRef}
          d=""
          fill="none"
          stroke="#ffffff"
          stroke-width={RUBBER_WIDTH}
          stroke-linecap="round"
          stroke-linejoin="round"
          opacity={0.7}
          style={{ display: "none" }}
        />

        {/* player tokens: flat disc + white border, like the desktop app */}
        {tokens.map((token) => (
          <g
            key={`${token.teamKey}-${token.playerId}`}
            data-team-key={token.teamKey}
            data-player-id={token.playerId}
            transform={`translate(${token.x} ${token.y})`}
            className="court-token"
          >
            {token.highlight ? (
              <circle
                cx={0}
                cy={0}
                r={TOKEN_RADIUS + 0.1}
                fill="none"
                stroke={SETTER_RING}
                stroke-width={0.125}
              />
            ) : null}
            <circle
              cx={0}
              cy={0}
              r={TOKEN_RADIUS}
              fill={token.color}
              stroke="#ffffff"
              stroke-width={0.05}
            />
            {token.badge !== "" ? (
              <text x={0} y={-0.38} className="court-token-badge" text-anchor="middle">
                {token.badge}
              </text>
            ) : null}
            <text x={0} y={0.18} className="court-token-number" text-anchor="middle">
              {token.number}
            </text>
            {token.serving ? (
              <circle
                cx={TOKEN_RADIUS - 0.05}
                cy={-TOKEN_RADIUS + 0.05}
                r={0.175}
                fill="#ffd600"
                stroke="#333333"
                stroke-width={0.025}
              />
            ) : null}
            <text x={0} y={TOKEN_RADIUS + 0.42} className="court-token-name" text-anchor="middle">
              {token.name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
