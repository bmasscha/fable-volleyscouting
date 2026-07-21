// Derived colours for player tokens, so the jersey colour (the user's free
// choice) never makes the number, badge or border unreadable, and the libero's
// mandatory contrasting jersey never clashes with the team colour.
//
// This is the 1:1 mirror of ui/token_colors.py -- same palette, same order,
// same maths. Keep the two files in lock-step.

export const BLACK = "#000000";
export const WHITE = "#ffffff";

// Curated jersey colours a libero might realistically wear. Deliberately
// EXCLUDES orange -- the court itself is orange (#e8853b), so an orange libero
// would blend into the floor. Order is significant: it breaks ties.
export const LIBERO_PALETTE = [
  "#d32f2f", // red
  "#fbc02d", // yellow
  "#7cb342", // lime
  "#00acc1", // teal
  "#1e88e5", // blue
  "#8e24aa", // purple
  "#d81b60", // magenta
  "#ffffff", // white
  "#212121", // near-black
] as const;

function rgb(hexColor: string): [number, number, number] {
  let h = hexColor.replace(/^#/, "");
  if (h.length === 3) {
    h = h
      .split("")
      .map((ch) => ch + ch)
      .join("");
  }
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function relativeLuminance(hexColor: string): number {
  const chan = (c: number): number => {
    const s = c / 255.0;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = rgb(hexColor);
  return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b);
}

// Black or white -- whichever has the higher WCAG contrast against `fill`.
// Use for the number, badge and disc border drawn on a coloured token.
export function inkFor(fill: string): string {
  const lum = relativeLuminance(fill);
  const contrastWhite = (1.0 + 0.05) / (lum + 0.05);
  const contrastBlack = (lum + 0.05) / 0.05;
  return contrastBlack >= contrastWhite ? BLACK : WHITE;
}

// The opposite of the ink colour -- a thin halo behind the glyph so the number
// stays crisp on muddy mid-tone jerseys where neither ink is ideal.
export function outlineFor(ink: string): string {
  return ink === BLACK ? WHITE : BLACK;
}

// Low-cost perceptual colour distance ('redmean'). Larger == more distinct.
function redmeanDistance(a: string, b: string): number {
  const [r1, g1, b1] = rgb(a);
  const [r2, g2, b2] = rgb(b);
  const rmean = (r1 + r2) / 2.0;
  const dr = r1 - r2;
  const dg = g1 - g2;
  const db = b1 - b2;
  return Math.sqrt(
    (2 + rmean / 256) * dr * dr +
      4 * dg * dg +
      (2 + (255 - rmean) / 256) * db * db,
  );
}

// Pick the palette colour most perceptually distinct from the team colour, so a
// red team never gets a red libero. Deterministic (ties -> palette order).
export function liberoColorFor(teamColor: string): string {
  let best: string = LIBERO_PALETTE[0];
  let bestDist = -1.0;
  for (const candidate of LIBERO_PALETTE) {
    const dist = redmeanDistance(candidate, teamColor);
    if (dist > bestDist) {
      best = candidate;
      bestDist = dist;
    }
  }
  return best;
}
