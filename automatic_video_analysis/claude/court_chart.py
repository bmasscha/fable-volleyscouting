"""Top-down volleyball serve-placement charts (camera-independent).

Three views, all drawn on the same canonical court (serving team at the BOTTOM,
receiving team at the TOP, net across the middle, receiving zones 1-6 marked):

- render_court_chart   : one arrow per serve, origin -> target, colored by team/player
- render_zone_heatmap  : smooth density of where serves land (great for a whole match)
- render_split_by_team : one arrow-panel per serving team, side by side

Input is court coordinates from trajectory.estimate_serve, defined relative to each
team's own orientation, so nothing here depends on the broadcast camera angle.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

_PALETTE = [
    (60, 180, 255), (0, 200, 0), (255, 130, 0), (200, 0, 255),
    (0, 200, 255), (255, 0, 130), (120, 200, 0), (0, 120, 255),
    (200, 200, 0), (150, 0, 200),
]

_BACK_ROW_ZONES = [1, 6, 5]    # nearest the receiving endline (top), image L->R
_FRONT_ROW_ZONES = [2, 3, 4]   # nearest the net, image L->R

_MARGIN, _CW, _CL, _TOP = 70, 340, 680, 46


def _clamp01(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, v))


def _color_key(s: dict, color_by: str) -> str:
    team = str(s.get("team") or s.get("label") or "?")
    player = str(s.get("player") or s.get("label") or "?")
    if color_by == "player":
        return f"{team} #{player}" if team != "?" else f"#{player}"
    return team


# --------------------------------------------------------------------------- #
# Court geometry / base drawing
# --------------------------------------------------------------------------- #
def _geom() -> dict:
    x0, y0 = _MARGIN, _MARGIN + _TOP
    return {"x0": x0, "y0": y0, "cw": _CW, "cl": _CL, "net_y": y0 + _CL // 2,
            "W": _CW + 2 * _MARGIN, "H": _CL + 2 * _MARGIN + _TOP}


def _new_court() -> tuple[np.ndarray, dict]:
    g = _geom()
    img = np.full((g["H"], g["W"], 3), 245, np.uint8)
    x0, y0, cw, cl, net_y = g["x0"], g["y0"], g["cw"], g["cl"], g["net_y"]
    cv2.rectangle(img, (x0, y0), (x0 + cw, y0 + cl), (150, 175, 200), -1)      # court tan
    cv2.rectangle(img, (x0, y0), (x0 + cw, net_y), (170, 195, 215), -1)        # receiving lighter
    return img, g


def _decorate(img: np.ndarray, g: dict):
    x0, y0, cw, cl, net_y = g["x0"], g["y0"], g["cw"], g["cl"], g["net_y"]
    white, line = (255, 255, 255), (70, 70, 70)
    cv2.rectangle(img, (x0, y0), (x0 + cw, y0 + cl), line, 2)
    cv2.line(img, (x0, net_y), (x0 + cw, net_y), (120, 60, 40), 4)             # net
    cv2.line(img, (x0, net_y - cl // 6), (x0 + cw, net_y - cl // 6), white, 1)  # recv attack line
    cv2.line(img, (x0, net_y + cl // 6), (x0 + cw, net_y + cl // 6), white, 1)  # serve attack line
    xb = [x0, x0 + cw // 3, x0 + 2 * cw // 3, x0 + cw]
    yb = [y0, y0 + cl // 4, net_y]
    for xi in xb[1:-1]:
        cv2.line(img, (xi, y0), (xi, net_y), (210, 210, 210), 1)
    cv2.line(img, (x0, yb[1]), (x0 + cw, yb[1]), (210, 210, 210), 1)
    for row, zones in enumerate((_BACK_ROW_ZONES, _FRONT_ROW_ZONES)):
        cy = (yb[row] + yb[row + 1]) // 2
        for col, z in enumerate(zones):
            cx = (xb[col] + xb[col + 1]) // 2
            cv2.putText(img, str(z), (cx - 8, cy + 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (185, 185, 185), 2, cv2.LINE_AA)
    cv2.putText(img, "RECEIVING", (x0 + 6, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 90, 90), 1, cv2.LINE_AA)
    cv2.putText(img, "SERVING", (x0 + 6, y0 + cl - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 90, 90), 1, cv2.LINE_AA)


def _origin_px(g: dict, from_lat) -> tuple[int, int]:
    return int(g["x0"] + _clamp01(from_lat) * g["cw"]), g["y0"] + g["cl"] - 6


def _target_px(g: dict, depth, lateral) -> tuple[int, int]:
    lat = 1.0 - _clamp01(lateral)  # receiver faces the other way -> mirror
    return int(g["x0"] + lat * g["cw"]), int(g["net_y"] - _clamp01(depth) * (g["cl"] / 2))


def _title(img, text):
    cv2.putText(img, text, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 2, cv2.LINE_AA)


# --------------------------------------------------------------------------- #
# Renderers (return an image array)
# --------------------------------------------------------------------------- #
def _render_arrows(serves: list[dict], color_by: str, title: str) -> tuple[np.ndarray, dict]:
    img, g = _new_court()
    _decorate(img, g)
    color_by_key: dict[str, tuple] = {}
    for s in serves:
        key = _color_key(s, color_by)
        col = color_by_key.setdefault(key, _PALETTE[len(color_by_key) % len(_PALETTE)])
        ox, oy = _origin_px(g, s.get("serve_from_lateral", 0.5))
        tx, ty = _target_px(g, s.get("target_depth", 0.5), s.get("target_lateral", 0.5))
        cv2.arrowedLine(img, (ox, oy), (tx, ty), col, 2, cv2.LINE_AA, tipLength=0.03)
        cv2.circle(img, (ox, oy), 5, col, 2, cv2.LINE_AA)
        cv2.circle(img, (tx, ty), 6, col, -1, cv2.LINE_AA)
    _title(img, title)
    lx = 12
    for key, col in color_by_key.items():
        cv2.rectangle(img, (lx, 34), (lx + 16, 44), col, -1)
        cv2.putText(img, key, (lx + 20, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1, cv2.LINE_AA)
        lx += 20 + 14 + 9 * len(key)
    return img, {"servers": list(color_by_key), "count": len(serves)}


def _render_heatmap(serves: list[dict], title: str) -> tuple[np.ndarray, dict]:
    img, g = _new_court()
    x0, y0, cw, net_y = g["x0"], g["y0"], g["cw"], g["net_y"]
    hh = net_y - y0  # receiving-half height
    dens = np.zeros((hh, cw), np.float32)
    for s in serves:
        tx, ty = _target_px(g, s.get("target_depth", 0.5), s.get("target_lateral", 0.5))
        r, c = ty - y0, tx - x0
        if 0 <= r < hh and 0 <= c < cw:
            dens[r, c] += 1.0
    if dens.max() > 0:
        sigma = max(8, min(hh, cw) // 10)
        dens = cv2.GaussianBlur(dens, (0, 0), sigma)
        dn = dens / dens.max()
        heat = cv2.applyColorMap((dn * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
        alpha = (dn * 0.75)[..., None]
        region = img[y0:net_y, x0:x0 + cw].astype(np.float32)
        img[y0:net_y, x0:x0 + cw] = (region * (1 - alpha) + heat.astype(np.float32) * alpha).astype(np.uint8)
    _decorate(img, g)
    # per-zone counts
    counts: dict[int, int] = {}
    for s in serves:
        z = int(s.get("target_zone") or 0)
        if z:
            counts[z] = counts.get(z, 0) + 1
    xb = [x0, x0 + cw // 3, x0 + 2 * cw // 3, x0 + cw]
    yb = [y0, y0 + g["cl"] // 4, net_y]
    for row, zones in enumerate((_BACK_ROW_ZONES, _FRONT_ROW_ZONES)):
        cy = (yb[row] + yb[row + 1]) // 2
        for col, z in enumerate(zones):
            cx = (xb[col] + xb[col + 1]) // 2
            if counts.get(z):
                cv2.putText(img, f"x{counts[z]}", (cx - 12, cy + 26), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (20, 20, 20), 2, cv2.LINE_AA)
    _title(img, title)
    cv2.putText(img, f"{len(serves)} serves", (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (30, 30, 30), 1, cv2.LINE_AA)
    return img, {"servers": [], "count": len(serves)}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _save(img, out_png, extra) -> dict:
    os.makedirs(os.path.dirname(os.path.abspath(out_png)) or ".", exist_ok=True)
    cv2.imwrite(out_png, img)
    return {"out_png": out_png, **extra}


def render_court_chart(serves: list[dict], out_png: str, color_by: str = "team",
                       title: str = "Serve placement (top-down, camera-independent)") -> dict:
    img, info = _render_arrows(serves, color_by, title)
    return _save(img, out_png, info)


def render_zone_heatmap(serves: list[dict], out_png: str,
                        title: str = "Serve landing heatmap") -> dict:
    img, info = _render_heatmap(serves, title)
    return _save(img, out_png, info)


def render_split_by_team(serves: list[dict], out_png: str, color_by: str = "player") -> dict:
    teams = sorted({str(s.get("team") or "?") for s in serves}) or ["?"]
    panels = []
    for t in teams:
        sub = [s for s in serves if str(s.get("team") or "?") == t]
        img, _ = _render_arrows(sub, color_by, f"{t}  (n={len(sub)})")
        panels.append(img)
    grid = np.hstack(panels) if panels else _render_arrows([], color_by, "no serves")[0]
    return _save(grid, out_png, {"teams": teams, "count": len(serves)})
