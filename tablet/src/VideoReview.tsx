/** Tablet video-review route (playback only -- no export).
 *
 * Loads a saved match, filters its actions (the shared query core), and plays
 * the matching 2 s-before / 5 s-after fragments of the bound video -- a local
 * file or a YouTube video. Sync anchors and the source pointer live in the
 * IndexedDB archive (matchStore), keyed by match id. */

import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";

import { MatchSnapshot } from "./browserStorage";
import { AWAY, HOME, RATINGS, Rating, Role, Skill, TeamKey, role_abbrev } from "./core/models";
import { Action, ActionFilter, build_actions, filter_actions } from "./core/query";
import {
  Anchor,
  FILE,
  VideoLink,
  YOUTUBE,
  clip_window,
  event_to_video_time,
  video_link,
  youtube_id,
} from "./core/videoSync";
import { getVideoLink, saveVideoLink } from "./matchStore";

const ANY = "";

interface PlayerHandle {
  seek: (seconds: number) => void;
  play: () => void;
  pause: () => void;
  currentTime: () => number;
}

interface YTPlayer {
  seekTo: (seconds: number, allowSeekAhead: boolean) => void;
  playVideo: () => void;
  pauseVideo: () => void;
  getCurrentTime: () => number;
}

// --- YouTube IFrame API (loaded once, lazily) -----------------------------

let ytApiPromise: Promise<void> | null = null;

function loadYouTubeApi(): Promise<void> {
  if (ytApiPromise != null) {
    return ytApiPromise;
  }
  ytApiPromise = new Promise((resolve) => {
    const w = window as unknown as { YT?: { Player?: unknown }; onYouTubeIframeAPIReady?: () => void };
    if (w.YT && w.YT.Player) {
      resolve();
      return;
    }
    w.onYouTubeIframeAPIReady = () => resolve();
    const tag = document.createElement("script");
    tag.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(tag);
  });
  return ytApiPromise;
}

function fmtTime(seconds: number | null): string {
  if (seconds == null) return "--:--";
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

interface VideoReviewProps {
  match: MatchSnapshot;
  onBack: () => void;
}

export function VideoReview({ match, onBack }: VideoReviewProps) {
  const actions = useMemo(() => build_actions(match.events, match.teams), [match]);

  const [team, setTeam] = useState<TeamKey | "">(ANY);
  const [playerId, setPlayerId] = useState<string>(ANY);
  const [role, setRole] = useState<Role | "">(ANY);
  const [skill, setSkill] = useState<Skill | "">(ANY);
  const [rating, setRating] = useState<Rating | "">(ANY);
  const [setNo, setSetNo] = useState<string>(ANY);

  const [link, setLink] = useState<VideoLink>(() => video_link());
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [ytUrl, setYtUrl] = useState("");
  const [ytReady, setYtReady] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const ytHostRef = useRef<HTMLDivElement | null>(null);
  const ytPlayerRef = useRef<YTPlayer | null>(null);
  const clipEndRef = useRef<number | null>(null);
  const queueRef = useRef<number[]>([]);

  // Load any stored link (anchors + source) for this match.
  useEffect(() => {
    let live = true;
    getVideoLink(match.id).then((stored) => {
      if (live && stored != null) {
        setLink(stored);
      }
    });
    return () => {
      live = false;
    };
  }, [match.id]);

  // Build the YouTube player when the source is a YouTube id.
  useEffect(() => {
    if (link.source_kind !== YOUTUBE || !link.source_ref) {
      return;
    }
    let cancelled = false;
    setYtReady(false);
    loadYouTubeApi().then(() => {
      if (cancelled || ytHostRef.current == null) return;
      const YT = (window as unknown as { YT: { Player: new (el: HTMLElement, cfg: unknown) => YTPlayer } }).YT;
      // YT.Player *replaces* the element we hand it with an <iframe>. Give it a
      // throwaway child so Preact keeps owning the wrapper div and never tries
      // to reconcile the node YouTube swapped out (which silently kills the
      // player -- the cause of "Load does nothing").
      ytHostRef.current.innerHTML = "";
      const host = document.createElement("div");
      ytHostRef.current.appendChild(host);
      ytPlayerRef.current = new YT.Player(host, {
        videoId: link.source_ref,
        host: "https://www.youtube.com",
        // origin is sometimes blocked by tablet webviews, so we omit it.
        // nocookie domain is also known to drop the onReady event in some setups.
        playerVars: { controls: 1, rel: 0, modestbranding: 1, playsinline: 1 },
        events: { onReady: () => { if (!cancelled) setYtReady(true); } },
      });
    });
    return () => {
      cancelled = true;
      setYtReady(false);
      try {
        (ytPlayerRef.current as unknown as { destroy?: () => void } | null)?.destroy?.();
      } catch {
        /* player may already be torn down */
      }
      ytPlayerRef.current = null;
    };
  }, [link.source_kind, link.source_ref]);

  const persist = useCallback((next: VideoLink) => {
    setLink(next);
    void saveVideoLink(match.id, next);
  }, [match.id]);

  const player = useCallback((): PlayerHandle | null => {
    if (link.source_kind === YOUTUBE) {
      const p = ytPlayerRef.current;
      if (p == null || !ytReady || typeof p.getCurrentTime !== "function") return null;
      return {
        seek: (s) => p.seekTo(s, true),
        play: () => p.playVideo(),
        pause: () => p.pauseVideo(),
        currentTime: () => p.getCurrentTime(),
      };
    }
    const v = videoRef.current;
    if (v == null) return null;
    return {
      seek: (s) => { v.currentTime = Math.max(0, s); },
      play: () => void v.play(),
      pause: () => v.pause(),
      currentTime: () => v.currentTime,
    };
  }, [link.source_kind, ytReady]);

  // Stop each clip at its end; chain the queue for "Play all".
  useEffect(() => {
    const id = window.setInterval(() => {
      const end = clipEndRef.current;
      const p = player();
      if (end == null || p == null) return;
      if (p.currentTime() >= end) {
        p.pause();
        clipEndRef.current = null;
        const nextIndex = queueRef.current.shift();
        if (nextIndex != null) {
          const nextAction = actions.find((a) => a.index === nextIndex);
          if (nextAction != null) playAction(nextAction);
        }
      }
    }, 120);
    return () => window.clearInterval(id);
    // playAction is stable enough for this interval; player captured via ref reads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player, actions]);

  const spec: ActionFilter = {
    team_key: team === ANY ? null : team,
    player_id: playerId === ANY ? null : playerId,
    role: role === ANY ? null : role,
    skill: skill === ANY ? null : skill,
    rating: rating === ANY ? null : rating,
    set_number: setNo === ANY ? null : Number(setNo),
  };
  const filtered = useMemo(() => filter_actions(actions, spec), [actions, team, playerId, role, skill, rating, setNo]);

  const sets = useMemo(() => Array.from(new Set(actions.map((a) => a.set_number))).sort((a, b) => a - b), [actions]);
  const players = useMemo(() => {
    const rows: { id: string; label: string }[] = [];
    for (const [key, label] of [[HOME, "Home"], [AWAY, "Away"]] as const) {
      const t = match.teams[key];
      if (t == null) continue;
      for (const p of [...t.players].sort((a, b) => a.number - b.number)) {
        rows.push({ id: p.id, label: `${label} #${p.number} ${p.name}` });
      }
    }
    return rows;
  }, [match]);

  function actionLabel(a: Action): string {
    const teamName = match.teams[a.team_key]?.name ?? a.team_key;
    return `S${a.set_number} · ${teamName} #${a.player_number ?? "?"} ${a.skill} ${a.rating}`;
  }

  function playAction(a: Action): void {
    const p = player();
    if (p == null) {
      setMessage(
        link.source_kind === YOUTUBE && Boolean(link.source_ref)
          ? "The video is still loading — give it a moment, then try again."
          : "Load a video first (choose a file or paste a YouTube URL).",
      );
      return;
    }
    const window_ = clip_window(link, a.ts);
    if (window_ == null) {
      setMessage("No sync anchor yet — tap this action, scrub the video to that moment, then “Sync here”.");
      return;
    }
    setMessage(null);
    const [start, end] = window_;
    clipEndRef.current = end;
    p.seek(start);
    p.play();
  }

  function onClipTap(a: Action): void {
    setSelectedIndex(a.index);
    queueRef.current = [];
    playAction(a);
  }

  function playAll(): void {
    if (filtered.length === 0) {
      setMessage("No matching actions to play — widen the filters.");
      return;
    }
    queueRef.current = filtered.slice(1).map((a) => a.index);
    setSelectedIndex(filtered[0]!.index);
    playAction(filtered[0]!);
  }

  function onPickFile(event: Event): void {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (file == null) return;
    if (objectUrl != null) URL.revokeObjectURL(objectUrl);
    setObjectUrl(URL.createObjectURL(file));
    persist({ ...link, source_kind: FILE, source_ref: file.name });
    input.value = "";
  }

  function onLoadYouTube(): void {
    const id = youtube_id(ytUrl);
    if (id == null) {
      setMessage("That does not look like a YouTube URL.");
      return;
    }
    setMessage("Loading the YouTube video…");
    setYtReady(false);
    ytPlayerRef.current = null;
    persist({ ...link, source_kind: YOUTUBE, source_ref: id });
  }

  function syncHere(): void {
    const a = selectedAction;
    const p = player();
    if (a == null || a.ts == null) {
      setMessage("First tap the action you are looking at in the list, then Sync here.");
      return;
    }
    if (p == null) {
      setMessage("The video is still loading — wait a moment, then Sync here.");
      return;
    }
    const at = p.currentTime();
    const anchor: Anchor = { event_ts: a.ts, video_seconds: at };
    persist({ ...link, anchors: [...link.anchors, anchor] });
    setMessage(`✓ Synced “${actionLabel(a)}” to video ${fmtTime(at)} — ${link.anchors.length + 1} anchor(s) set.`);
  }

  function removeAnchor(i: number): void {
    persist({ ...link, anchors: link.anchors.filter((_, idx) => idx !== i) });
  }

  const selectedAction = selectedIndex == null ? null : actions.find((x) => x.index === selectedIndex) ?? null;
  const hasSource = Boolean(link.source_ref) && (link.source_kind !== FILE || objectUrl != null);
  const canSync = hasSource && selectedAction != null && (link.source_kind !== YOUTUBE || ytReady);
  const ytDeepLink =
    link.source_kind === YOUTUBE && link.source_ref && selectedAction != null
      ? `https://www.youtube.com/watch?v=${link.source_ref}&t=${Math.max(
          0,
          Math.floor((event_to_video_time(link, selectedAction.ts) ?? 0) - link.pre_roll),
        )}s`
      : null;

  // Memoize the YouTube host container so Preact never diffs its children 
  // (which would remove the iframe that YouTube's API inserts).
  const ytHostNode = useMemo(() => <div className="vr-yt" ref={ytHostRef} />, []);

  return (
    <main className="shell video-review">
      <section className="startup-card video-review-card">
        <div className="library-header">
          <h1>Video review</h1>
          <div className="button-row">
            <button type="button" onClick={onBack}>Back</button>
          </div>
        </div>
        <p className="muted">
          {match.teams[HOME].name} vs {match.teams[AWAY].name} · {actions.length} actions
        </p>
        {message != null ? <div className="message-banner">{message}</div> : null}

        <div className="video-review-body">
          {/* filters */}
          <div className="vr-filters">
            <label>Team
              <select value={team} onChange={(e) => setTeam((e.currentTarget as HTMLSelectElement).value as TeamKey | "")}>
                <option value="">— any —</option>
                <option value={HOME}>Home</option>
                <option value={AWAY}>Away</option>
              </select>
            </label>
            <label>Player
              <select value={playerId} onChange={(e) => setPlayerId((e.currentTarget as HTMLSelectElement).value)}>
                <option value="">— any —</option>
                {players.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </label>
            <label>Role
              <select value={role} onChange={(e) => setRole((e.currentTarget as HTMLSelectElement).value as Role | "")}>
                <option value="">— any —</option>
                {Object.values(Role).map((r) => <option key={r} value={r}>{role_abbrev(r)} · {r}</option>)}
              </select>
            </label>
            <label>Skill
              <select value={skill} onChange={(e) => setSkill((e.currentTarget as HTMLSelectElement).value as Skill | "")}>
                <option value="">— any —</option>
                {Object.values(Skill).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label>Rating
              <select value={rating} onChange={(e) => setRating((e.currentTarget as HTMLSelectElement).value as Rating | "")}>
                <option value="">— any —</option>
                {RATINGS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label>Set
              <select value={setNo} onChange={(e) => setSetNo((e.currentTarget as HTMLSelectElement).value)}>
                <option value="">— any —</option>
                {sets.map((s) => <option key={s} value={String(s)}>{s}</option>)}
              </select>
            </label>
          </div>

          {/* player */}
          <div className="vr-player">
            {link.source_kind === YOUTUBE ? (
              ytHostNode
            ) : objectUrl != null ? (
              <video ref={videoRef} src={objectUrl} controls className="vr-video" />
            ) : (
              <div className="vr-placeholder">Choose a video file or paste a YouTube URL.</div>
            )}
            <div className="vr-source-controls button-row">
              <label className="vr-file-btn">
                Video file…
                <input type="file" accept="video/*" style={{ display: "none" }} onChange={onPickFile} />
              </label>
              <input
                type="text"
                placeholder="YouTube URL"
                value={ytUrl}
                onInput={(e) => setYtUrl((e.currentTarget as HTMLInputElement).value)}
              />
              <button type="button" onClick={onLoadYouTube}>Load</button>
            </div>

            {/* Sync panel -- kept next to the button so the confirmation is
                visible on the tablet (the top banner scrolls out of view). */}
            <div className="vr-sync">
              <div className="vr-sync-target muted">
                {selectedAction != null
                  ? <>Selected: <strong>{actionLabel(selectedAction)}</strong></>
                  : "Tap an action in the list to select it."}
              </div>
              <div className="button-row">
                <button type="button" className="primary" onClick={syncHere} disabled={!canSync}>
                  Sync here
                </button>
                {ytDeepLink != null ? (
                  <a className="vr-yt-open" href={ytDeepLink} target="_blank" rel="noreferrer">
                    Open in YouTube
                  </a>
                ) : null}
                {link.source_kind === YOUTUBE && Boolean(link.source_ref) ? (
                  <button 
                    type="button" 
                    className="vr-yt-login"
                    title="Log into YouTube to remove ads if you have YouTube Premium"
                    onClick={() => window.open("https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com", "yt_login", "width=600,height=800")}
                  >
                    Log in (Remove Ads)
                  </button>
                ) : null}
              </div>
              {link.source_kind === YOUTUBE && Boolean(link.source_ref) && !ytReady ? (
                <p className="muted">Video loading…</p>
              ) : null}
            </div>

            <div className="vr-anchors">
              <div className="muted">
                {link.anchors.length} anchor(s) · {link.source_ref
                  ? (link.source_kind === YOUTUBE ? `YouTube ${link.source_ref}` : link.source_ref)
                  : "no video"}
              </div>
              {link.anchors.length > 0 ? (
                <ul className="vr-anchor-list">
                  {[...link.anchors]
                    .map((anchor, i) => ({ anchor, i }))
                    .sort((x, y) => x.anchor.video_seconds - y.anchor.video_seconds)
                    .map(({ anchor, i }) => (
                      <li key={i}>
                        <span className="muted">video {fmtTime(anchor.video_seconds)}</span>
                        <button type="button" className="vr-anchor-del" onClick={() => removeAnchor(i)}>
                          remove
                        </button>
                      </li>
                    ))}
                </ul>
              ) : null}
            </div>
          </div>

          {/* clip list */}
          <div className="vr-clips">
            <div className="vr-clips-header">
              <strong>{filtered.length} matching</strong>
              <button type="button" onClick={playAll} disabled={filtered.length === 0}>Play all</button>
            </div>
            <ul className="match-list">
              {filtered.map((a) => {
                const vt = event_to_video_time(link, a.ts);
                const teamName = match.teams[a.team_key]?.name ?? a.team_key;
                return (
                  <li
                    key={a.index}
                    className={`vr-clip-row${a.index === selectedIndex ? " selected" : ""}`}
                    onClick={() => onClipTap(a)}
                  >
                    <span>S{a.set_number} · {teamName} #{a.player_number ?? "?"} {a.player_name}</span>
                    <span className="muted">{a.skill} {a.rating} · {vt == null ? "unsynced" : `@ ${fmtTime(vt)}`}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </section>
    </main>
  );
}
