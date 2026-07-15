import { useEffect, useMemo, useState } from "preact/hooks";

import { MatchEvent } from "./core/events";
import {
  ReportSortKey,
  REPORT_SORT_KEY,
  ReportPlayerRow,
  ReportTeamSection,
  buildReportSections,
  sortReportRows,
} from "./core/reporting";
import {
  ACES,
  KILLS,
  MANUAL_OTHER,
  OPPONENT_ERRORS,
  compute_stats,
  export_csv,
  export_html,
} from "./core/stats";
import {
  TrajectoryStat,
  collect_trajectories,
  filter_trajectories,
  outcome,
  summarize_trajectories,
} from "./core/trajectories";
import {
  AWAY,
  HOME,
  MatchConfig,
  Rating,
  Skill,
  Team,
  TeamKey,
  TEAM_KEYS,
} from "./core/models";
import {
  ATTACK_LINE,
  COURT_HALF_LENGTH,
  COURT_WIDTH,
  FREE_ZONE_X,
  FREE_ZONE_Y,
} from "./core/rotation";

const ALL_PLAYERS = "__all__";
const ALL_SETS = 0;
const NON_SCALING_STROKE = "non-scaling-stroke";

const REPORT_SORT_OPTIONS: readonly { key: ReportSortKey; label: string }[] = [
  { key: REPORT_SORT_KEY.NUMBER, label: "Jersey number" },
  { key: REPORT_SORT_KEY.NAME, label: "Player name" },
  { key: REPORT_SORT_KEY.POINTS, label: "Direct points" },
  { key: REPORT_SORT_KEY.TOTAL_ACTIONS, label: "Total actions" },
  { key: REPORT_SORT_KEY.SERVE_TOTAL, label: "Serve touches" },
  { key: REPORT_SORT_KEY.SERVE_EFFICIENCY, label: "Serve efficiency" },
  { key: REPORT_SORT_KEY.RECEPTION_POSITIVE, label: "Reception positive %" },
  { key: REPORT_SORT_KEY.ATTACK_TOTAL, label: "Attack touches" },
  { key: REPORT_SORT_KEY.ATTACK_KILL_PCT, label: "Attack kill %" },
  { key: REPORT_SORT_KEY.ATTACK_EFFICIENCY, label: "Attack efficiency" },
  { key: REPORT_SORT_KEY.DIG_TOTAL, label: "Dig touches" },
];

function formatPercent(value: number): string {
  return value.toFixed(1);
}

function chartId(title: string): string {
  return `trajectory-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function teamName(teams: Record<TeamKey, Team>, teamKey: TeamKey): string {
  return teams[teamKey].name;
}

function safeFilePart(text: string): string {
  const slug = text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug === "" ? "team" : slug;
}

function matchFileStem(teams: Record<TeamKey, Team>): string {
  return `${safeFilePart(teams[HOME].name)}-vs-${safeFilePart(teams[AWAY].name)}`;
}

function downloadTextFile(filename: string, mimeType: string, text: string): void {
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

interface ReportPanelProps {
  teams: Record<TeamKey, Team>;
  events: MatchEvent[];
  onClose: () => void;
}

interface TeamReportCardProps {
  section: ReportTeamSection;
}

function TeamReportCard({ section }: TeamReportCardProps) {
  const [sortKey, setSortKey] = useState<ReportSortKey>(REPORT_SORT_KEY.NUMBER);
  const [sortDescending, setSortDescending] = useState(false);

  const rows = section.activeRows.length > 0 ? section.activeRows : section.rows;
  const sortedRows = useMemo(
    () => sortReportRows(rows, sortKey, sortDescending),
    [rows, sortDescending, sortKey],
  );

  return (
    <article className="control-card report-team-card" style={{ borderColor: section.team.color }}>
      <div className="screen-header report-card-header">
        <div>
          <h3>{section.team.name}</h3>
          <p className="muted">
            {section.activeRows.length > 0
              ? `${section.activeRows.length} active player(s)`
              : `${section.rows.length} rostered player(s)`}
          </p>
        </div>
        <div className="report-toolbar">
          <label>
            Sort players
            <select
              value={sortKey}
              onChange={(event) => setSortKey((event.currentTarget as HTMLSelectElement).value as ReportSortKey)}
            >
              {REPORT_SORT_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => setSortDescending((current) => !current)}>
            {sortDescending ? "Descending" : "Ascending"}
          </button>
        </div>
      </div>

      <div className="report-breakdown-grid">
        <div className="breakdown-card">
          <strong>{section.totalPoints}</strong>
          <span className="muted">Total points</span>
        </div>
        <div className="breakdown-card">
          <strong>{section.pointsBreakdown[ACES]}</strong>
          <span className="muted">Aces</span>
        </div>
        <div className="breakdown-card">
          <strong>{section.pointsBreakdown[KILLS]}</strong>
          <span className="muted">Kills</span>
        </div>
        <div className="breakdown-card">
          <strong>{section.pointsBreakdown[OPPONENT_ERRORS]}</strong>
          <span className="muted">Opponent errors</span>
        </div>
        <div className="breakdown-card">
          <strong>{section.pointsBreakdown[MANUAL_OTHER]}</strong>
          <span className="muted">Manual / other</span>
        </div>
      </div>

      <div className="report-table-wrap">
        <table className="report-table">
          <thead>
            <tr>
              <th>#</th>
              <th className="player-col">Player</th>
              <th>Role</th>
              <th>Srv tot</th>
              <th>Srv !</th>
              <th>Srv -</th>
              <th>Srv +</th>
              <th>Srv #</th>
              <th>Srv eff%</th>
              <th>Rec tot</th>
              <th>Rec !</th>
              <th>Rec -</th>
              <th>Rec +</th>
              <th>Rec #</th>
              <th>Rec pos%</th>
              <th>Att tot</th>
              <th>Att !</th>
              <th>Att -</th>
              <th>Att +</th>
              <th>Att #</th>
              <th>Kill%</th>
              <th>Att eff%</th>
              <th>Dig tot</th>
              <th>Dig !</th>
              <th>Dig -</th>
              <th>Dig +</th>
              <th>Dig #</th>
              <th>Points</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row) => renderReportRow(row))}
            {renderReportRow(section.totalRow, "report-total-row")}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function renderReportRow(row: ReportPlayerRow, className = "") {
  const serve = row.skills[Skill.SERVE];
  const reception = row.skills[Skill.RECEPTION];
  const attack = row.skills[Skill.ATTACK];
  const dig = row.skills[Skill.DIG];
  return (
    <tr key={`${row.playerId ?? "total"}-${className}`} className={className}>
      <td>{row.number ?? ""}</td>
      <td className="player-cell">{row.name}</td>
      <td>{row.roleAbbrev}</td>
      <td>{serve.total}</td>
      <td>{serve.count(Rating.ERROR)}</td>
      <td>{serve.count(Rating.POOR)}</td>
      <td>{serve.count(Rating.GOOD)}</td>
      <td>{serve.count(Rating.PERFECT)}</td>
      <td>{formatPercent(serve.efficiency)}</td>
      <td>{reception.total}</td>
      <td>{reception.count(Rating.ERROR)}</td>
      <td>{reception.count(Rating.POOR)}</td>
      <td>{reception.count(Rating.GOOD)}</td>
      <td>{reception.count(Rating.PERFECT)}</td>
      <td>{formatPercent(reception.positive_pct)}</td>
      <td>{attack.total}</td>
      <td>{attack.count(Rating.ERROR)}</td>
      <td>{attack.count(Rating.POOR)}</td>
      <td>{attack.count(Rating.GOOD)}</td>
      <td>{attack.count(Rating.PERFECT)}</td>
      <td>{formatPercent(attack.pct(Rating.PERFECT))}</td>
      <td>{formatPercent(attack.efficiency)}</td>
      <td>{dig.total}</td>
      <td>{dig.count(Rating.ERROR)}</td>
      <td>{dig.count(Rating.POOR)}</td>
      <td>{dig.count(Rating.GOOD)}</td>
      <td>{dig.count(Rating.PERFECT)}</td>
      <td>{row.points}</td>
    </tr>
  );
}

export function ReportPanel({ teams, events, onClose }: ReportPanelProps) {
  const stats = useMemo(() => compute_stats(events, teams), [events, teams]);
  const sections = useMemo(() => buildReportSections(stats, teams), [stats, teams]);
  const fileStem = useMemo(() => matchFileStem(teams), [teams]);

  return (
    <section className="editor-shell insights-panel">
      <div className="screen-header">
        <div>
          <h2>Match report</h2>
          <p className="muted">Live stats update on every rerender. Use the exports for quick sharing or offline review.</p>
        </div>
        <div className="button-row compact">
          <button
            type="button"
            onClick={() => downloadTextFile(`${fileStem}-report.csv`, "text/csv;charset=utf-8", export_csv(stats, teams))}
          >
            Export CSV
          </button>
          <button
            type="button"
            onClick={() => downloadTextFile(`${fileStem}-report.html`, "text/html;charset=utf-8", export_html(stats, teams))}
          >
            Export HTML
          </button>
          <button type="button" className="ghost" onClick={onClose}>
            Close report
          </button>
        </div>
      </div>

      {sections.map((section) => (
        <TeamReportCard key={section.teamKey} section={section} />
      ))}
    </section>
  );
}

interface TrajectoryPanelProps {
  config: MatchConfig;
  teams: Record<TeamKey, Team>;
  events: MatchEvent[];
  onClose: () => void;
}

interface TrajectoryCourtProps {
  title: string;
  lines: TrajectoryStat[];
  pointLabel: string;
}

function lineColor(stat: TrajectoryStat): string {
  const result = outcome(stat.rating);
  if (result === "point") {
    return "#43a047";
  }
  if (result === "error") {
    return "#e53935";
  }
  return "#ffffff";
}

/** Arrowhead at (x2, y2) pointing along the segment (x1, y1) -> (x2, y2).
 * For a blocked attack, pass the last segment (vertex -> end). */
function arrowHeadPoints(x1: number, y1: number, x2: number, y2: number): string {
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const head = Math.min(0.62, Math.hypot(x2 - x1, y2 - y1) * 0.22);
  const leftX = x2 + head * Math.cos(angle + Math.PI - Math.PI / 7);
  const leftY = y2 + head * Math.sin(angle + Math.PI - Math.PI / 7);
  const rightX = x2 + head * Math.cos(angle + Math.PI + Math.PI / 7);
  const rightY = y2 + head * Math.sin(angle + Math.PI + Math.PI / 7);
  return `${x2},${y2} ${leftX},${leftY} ${rightX},${rightY}`;
}

function TrajectoryCourt({ title, lines, pointLabel }: TrajectoryCourtProps) {
  const summary = useMemo(() => summarize_trajectories(lines), [lines]);
  const minX = -COURT_HALF_LENGTH - FREE_ZONE_X;
  const minY = -FREE_ZONE_Y;
  const width = 2 * (COURT_HALF_LENGTH + FREE_ZONE_X);
  const height = COURT_WIDTH + 2 * FREE_ZONE_Y;
  const id = chartId(title);

  return (
    <article className="control-card trajectory-chart-card">
      <div>
        <h3>{title}</h3>
        <p className="muted">
          {summary.total} total Â· {summary.points} {pointLabel}
          {summary.points === 1 ? "" : "s"} Â· {summary.errors} fault{summary.errors === 1 ? "" : "s"}
        </p>
      </div>
      <svg
        className="trajectory-svg"
        viewBox={`${minX} ${minY} ${width} ${height}`}
        role="img"
        aria-label={`${title} trajectory chart`}
      >
        <defs>
          <linearGradient id={`${id}-free-zone`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#3a7fa8" />
            <stop offset="100%" stopColor="#20536d" />
          </linearGradient>
          <linearGradient id={`${id}-court`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#ef9a57" />
            <stop offset="100%" stopColor="#d97632" />
          </linearGradient>
          <linearGradient id={`${id}-attack-zone`} x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor="#df7a38" />
            <stop offset="100%" stopColor="#c86022" />
          </linearGradient>
        </defs>
        <rect x={minX} y={minY} width={width} height={height} fill={`url(#${id}-free-zone)`} />
        <rect x={-COURT_HALF_LENGTH} y="0" width={COURT_HALF_LENGTH * 2} height={COURT_WIDTH} fill={`url(#${id}-court)`} />
        <rect x={-ATTACK_LINE} y="0" width={ATTACK_LINE * 2} height={COURT_WIDTH} fill={`url(#${id}-attack-zone)`} />
        <rect
          x={-COURT_HALF_LENGTH}
          y="0"
          width={COURT_HALF_LENGTH * 2}
          height={COURT_WIDTH}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          stroke-width="3.2"
          vector-effect={NON_SCALING_STROKE}
        />
        <rect
          x={-COURT_HALF_LENGTH}
          y="0"
          width={COURT_HALF_LENGTH * 2}
          height={COURT_WIDTH}
          fill="none"
          stroke="rgba(255,255,255,0.92)"
          stroke-width="0.9"
          vector-effect={NON_SCALING_STROKE}
        />
        <line
          x1={-ATTACK_LINE}
          y1="0"
          x2={-ATTACK_LINE}
          y2={COURT_WIDTH}
          stroke="rgba(255,255,255,0.9)"
          stroke-width="0.9"
          vector-effect={NON_SCALING_STROKE}
        />
        <line
          x1={ATTACK_LINE}
          y1="0"
          x2={ATTACK_LINE}
          y2={COURT_WIDTH}
          stroke="rgba(255,255,255,0.9)"
          stroke-width="0.9"
          vector-effect={NON_SCALING_STROKE}
        />
        <line
          x1="0"
          y1={-0.6}
          x2="0"
          y2={COURT_WIDTH + 0.6}
          stroke="rgba(22, 28, 34, 0.95)"
          stroke-width="1.2"
          vector-effect={NON_SCALING_STROKE}
        />
        {lines.map((stat, index) => {
          const [x1, y1, x2, y2] = stat.line;
          const color = lineColor(stat);
          // last segment feeding the arrowhead: vertex -> end for a
          // blocked attack, otherwise the whole line.
          const [fx, fy] = stat.block_touch != null ? stat.block_touch : [x1, y1];
          return (
            <g key={`${stat.player_id}-${stat.set_number}-${index}`}>
              {stat.block_touch != null ? (
                <polyline
                  points={`${x1},${y1} ${stat.block_touch[0]},${stat.block_touch[1]} ${x2},${y2}`}
                  fill="none"
                  stroke={color}
                  stroke-width="1.1"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  vector-effect={NON_SCALING_STROKE}
                />
              ) : (
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={color}
                  stroke-width="1.1"
                  stroke-linecap="round"
                  vector-effect={NON_SCALING_STROKE}
                />
              )}
              {stat.block_touch != null ? (
                <circle cx={stat.block_touch[0]} cy={stat.block_touch[1]} r={0.22} fill={color} />
              ) : null}
              <polygon points={arrowHeadPoints(fx, fy, x2, y2)} fill={color} />
            </g>
          );
        })}
      </svg>
    </article>
  );
}

export function TrajectoryPanel({ config, teams, events, onClose }: TrajectoryPanelProps) {
  const [teamKey, setTeamKey] = useState<TeamKey>(HOME);
  const [playerId, setPlayerId] = useState<string>(ALL_PLAYERS);
  const [setNumber, setSetNumber] = useState<number>(ALL_SETS);

  const trajectories = useMemo(() => collect_trajectories(config, teams, events), [config, events, teams]);
  const availableSets = useMemo(
    () => [...new Set(trajectories.map((stat) => stat.set_number))].sort((left, right) => left - right),
    [trajectories],
  );
  const playerOptions = useMemo(
    () => [...teams[teamKey].players].sort((left, right) => left.number - right.number),
    [teamKey, teams],
  );

  useEffect(() => {
    if (!TEAM_KEYS.includes(teamKey)) {
      setTeamKey(HOME);
    }
  }, [teamKey]);

  useEffect(() => {
    if (playerId !== ALL_PLAYERS && !playerOptions.some((player) => player.id === playerId)) {
      setPlayerId(ALL_PLAYERS);
    }
  }, [playerId, playerOptions]);

  useEffect(() => {
    if (setNumber !== ALL_SETS && !availableSets.includes(setNumber)) {
      setSetNumber(ALL_SETS);
    }
  }, [availableSets, setNumber]);

  const filtered = useMemo(() => filter_trajectories(trajectories, {
    team: teamKey,
    player_id: playerId === ALL_PLAYERS ? null : playerId,
    set_number: setNumber === ALL_SETS ? null : setNumber,
  }), [playerId, setNumber, teamKey, trajectories]);

  const serves = useMemo(
    () => filter_trajectories(filtered, { skill: Skill.SERVE }),
    [filtered],
  );
  const attacks = useMemo(
    () => filter_trajectories(filtered, { skill: Skill.ATTACK }),
    [filtered],
  );

  return (
    <section className="editor-shell insights-panel">
      <div className="screen-header">
        <div>
          <h2>Trajectory analysis</h2>
          <p className="muted">All charts are normalized so the selected team always plays left to right.</p>
        </div>
        <div className="button-row compact">
          <button type="button" className="ghost" onClick={onClose}>
            Close charts
          </button>
        </div>
      </div>

      <div className="trajectory-filter-grid">
        <label>
          Team
          <select value={teamKey} onChange={(event) => setTeamKey((event.currentTarget as HTMLSelectElement).value as TeamKey)}>
            {TEAM_KEYS.map((key) => (
              <option key={key} value={key}>
                {teamName(teams, key)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Player
          <select value={playerId} onChange={(event) => setPlayerId((event.currentTarget as HTMLSelectElement).value)}>
            <option value={ALL_PLAYERS}>All players</option>
            {playerOptions.map((player) => (
              <option key={player.id} value={player.id}>
                #{player.number} {player.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Set
          <select value={String(setNumber)} onChange={(event) => setSetNumber(Number((event.currentTarget as HTMLSelectElement).value))}>
            <option value={String(ALL_SETS)}>All sets</option>
            {availableSets.map((value) => (
              <option key={value} value={String(value)}>
                Set {value}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="trajectory-legend">
        <span className="muted">Left â†’ right</span>
        <span className="trajectory-legend-item">
          <span className="trajectory-legend-swatch" style={{ background: "#43a047" }} />
          Point
        </span>
        <span className="trajectory-legend-item">
          <span className="trajectory-legend-swatch" style={{ background: "#e53935" }} />
          Error
        </span>
        <span className="trajectory-legend-item">
          <span className="trajectory-legend-swatch" style={{ background: "#ffffff" }} />
          Neutral
        </span>
      </div>

      <div className="trajectory-charts">
        <TrajectoryCourt title="Serves" lines={serves} pointLabel="ace" />
        <TrajectoryCourt title="Attacks" lines={attacks} pointLabel="kill" />
      </div>
    </section>
  );
}
