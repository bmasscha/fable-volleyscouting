# Releasing the tablet app

The tablet app is a fully client-side PWA: one static build serves both
Android and iPad, matches are stored in the browser (localStorage) on the
device, and after the first visit it works offline (the service worker
precaches the whole build).

## 1. Sync with the Python core (release contract)

The Python `core/` is the reference implementation. If anything in `core/`
changed since the last tablet release:

```powershell
# from the repo root
.venv\Scripts\python.exe -m pytest tests -q          # Python suite green
.venv\Scripts\python.exe tools\gen_conformance.py    # regenerate golden fixtures
npm --prefix tablet run test                         # TS suite (incl. conformance) green
```

Port any `core/` diffs to `tablet/src/core/` per `TRANSLATION.md` until the
conformance tests pass unchanged. **Never release with a red conformance
suite.**

## 2. Build

```powershell
npm --prefix tablet run build
```

Output lands in `tablet/dist/` — `index.html`, hashed assets, the icons,
`manifest.webmanifest`, and the service worker (`sw.js` + workbox runtime).
The build fails on TypeScript errors (`tsc --noEmit` runs first).

Icons live in `tablet/public/icons/` and are generated from
`tablet/public/favicon.svg`. Only regenerate them if the artwork changes
(render the SVG at 192/512 px, plus a padded 512 px maskable variant and a
180 px apple-touch-icon).

## 3. Deploy

Host the contents of `tablet/dist/` as static files. **PWA install and the
service worker require HTTPS** (plain `http://` only works for `localhost`).
The build assumes it is served from the site root; if it must live under a
subpath (e.g. GitHub Pages project sites), set `base` in `vite.config.ts`
and rebuild.

Options, easiest first:

- **Static host with HTTPS** (Netlify / Cloudflare Pages / GitHub Pages):
  drag-and-drop or push `tablet/dist/`. This is the recommended route — the
  app contains no secrets and no match data ever leaves the tablet.
- **Android via USB, no hosting:** `adb reverse tcp:4173 tcp:4173`, run
  `npm --prefix tablet run preview`, then open `http://localhost:4173` in
  Chrome on the tablet — localhost counts as a secure context, so install
  and offline mode work. The reverse survives until the cable is unplugged;
  after that the installed app keeps working offline.
- **Quick LAN eyeballing (no install):**
  `npm --prefix tablet run preview -- --host` and open
  `http://<pc-ip>:4173` on the tablet. The app runs, but over plain http the
  service worker will not register — no install prompt, no offline.

## 4. Install on the device

- **Android (Chrome):** open the URL → ⋮ menu → *Add to Home screen* /
  *Install app*. Launches full-screen (standalone, landscape).
- **iPad (Safari):** open the URL → Share → *Add to Home Screen*.

After the first successful load the app works with no network. Updates are
picked up automatically: on the next visit *with* connectivity the new
service worker installs and the app refreshes itself (`registerType:
"autoUpdate"`).

## 5. Post-deploy smoke test (on device)

1. Launch from the home-screen icon — full screen, dark theme, no browser UI.
2. Create a match, log a few rallies, check score/rotation.
3. Enable airplane mode, kill and relaunch the app — it must load and the
   match must still be there (browser storage is per-origin: clearing site
   data deletes saved teams/matches).
