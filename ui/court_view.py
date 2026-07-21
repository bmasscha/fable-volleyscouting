"""Horizontal volleyball court with free zone, player tokens and
trajectory input.

Interaction model (mouse and touch behave the same):
- press-drag-release across a meaningful distance -> trajectory_drawn
- short tap on a player token -> player_tapped
- short tap elsewhere -> court_tapped

Scene coordinates are court metres * M pixels; net at x = 0,
court y in [0, 9] (see core/rotation.py).
"""
from __future__ import annotations

from PyQt6.QtCore import (QLineF, QPointF, QRectF, Qt, QTimer,
                          QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QPainter, QPainterPath, QPen,
                         QPolygonF)
from PyQt6.QtWidgets import (QGraphicsEllipseItem, QGraphicsPathItem,
                             QGraphicsScene, QGraphicsView)

from core.rotation import (ATTACK_LINE, COURT_HALF_LENGTH, COURT_WIDTH,
                           FREE_ZONE_X, FREE_ZONE_Y)
from .player_token import PlayerToken

M = 40.0                       # pixels per metre
TAP_THRESHOLD_PX = 18.0        # press/release closer than this = tap

FREE_ZONE_COLOR = QColor("#2a6f97")
COURT_COLOR = QColor("#e8853b")
FRONT_ZONE_COLOR = QColor("#d9702a")
LINE_PEN = QPen(QColor("white"), 3)
NET_PEN = QPen(QColor("#222222"), 7)

SERVE_ARROW = QColor("#ffffff")
ATTACK_ARROW = QColor("#ffd600")

# Once the rally is over the arrows stay briefly, then fade away
# (mirrored by the tablet's CourtSurface ARROW_FADE transition).
FADE_DELAY_MS = 350
FADE_DURATION_MS = 650


class _Arrow(QGraphicsPathItem):
    def __init__(self, x1, y1, x2, y2, color: QColor, width: float = 4.0,
                 vertex: QPointF | None = None):
        super().__init__()
        # A blocked attack bends at `vertex` (the net contact): the path runs
        # start -> vertex -> end, arrowhead on the final segment only.
        start = QPointF(x1, y1)
        path = QPainterPath(start)
        if vertex is not None:
            path.lineTo(vertex)
        line = QLineF(vertex if vertex is not None else start, QPointF(x2, y2))
        path.lineTo(line.p2())
        # arrowhead (open wings, direction vertex/start -> end)
        head = QLineF(line.p2(), line.p1())
        head.setLength(min(16.0, line.length()))
        for angle in (-25, 25):
            wing = QLineF(head)
            wing.setAngle(head.angle() + angle)
            path.moveTo(line.p2())
            path.lineTo(wing.p2())
        self.setPath(path)
        self.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                         Qt.PenCapStyle.RoundCap))
        self.setZValue(5)
        if vertex is not None:                # filled dot marks the block touch
            r = 4.0
            dot = QGraphicsEllipseItem(vertex.x() - r, vertex.y() - r,
                                       2 * r, 2 * r, self)
            dot.setBrush(QBrush(color))
            dot.setPen(QPen(Qt.PenStyle.NoPen))


class CourtView(QGraphicsView):
    trajectory_drawn = pyqtSignal(float, float, float, float)  # court metres
    player_tapped = pyqtSignal(str, str)                       # team_key, player_id
    court_tapped = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(
            -(COURT_HALF_LENGTH + FREE_ZONE_X) * M, -FREE_ZONE_Y * M,
            2 * (COURT_HALF_LENGTH + FREE_ZONE_X) * M,
            (COURT_WIDTH + 2 * FREE_ZONE_Y) * M)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self._tokens: dict[tuple[str, str], PlayerToken] = {}
        self._arrows: list[_Arrow] = []
        self._press_scene: QPointF | None = None
        self._rubber: _Arrow | None = None
        self._fade_delay = QTimer(self)
        self._fade_delay.setSingleShot(True)
        self._fade_delay.setInterval(FADE_DELAY_MS)
        self._fade_delay.timeout.connect(self._start_fade)
        self._fade_anim: QVariantAnimation | None = None

    # ------------------------------------------------------------- painting

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, FREE_ZONE_COLOR)
        L, W, A = COURT_HALF_LENGTH * M, COURT_WIDTH * M, ATTACK_LINE * M
        court = QRectF(-L, 0, 2 * L, W)
        painter.fillRect(court, COURT_COLOR)
        painter.fillRect(QRectF(-A, 0, 2 * A, W), FRONT_ZONE_COLOR)
        painter.setPen(LINE_PEN)
        painter.drawRect(court)
        painter.drawLine(QPointF(-A, 0), QPointF(-A, W))   # attack lines
        painter.drawLine(QPointF(A, 0), QPointF(A, W))
        painter.setPen(NET_PEN)                            # net / centre line
        painter.drawLine(QPointF(0, -0.6 * M), QPointF(0, W + 0.6 * M))
        painter.setPen(QPen(QColor("white"), 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(0, 0), QPointF(0, W))

    # ---------------------------------------------------------------- input

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_scene = self.mapToScene(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_scene is not None:
            cur = self.mapToScene(event.position().toPoint())
            if (QLineF(self._press_scene, cur).length() > TAP_THRESHOLD_PX):
                if self._rubber is not None:
                    self._scene.removeItem(self._rubber)
                self._rubber = _Arrow(self._press_scene.x(), self._press_scene.y(),
                                      cur.x(), cur.y(), QColor("#ffffff"), 3.0)
                self._rubber.setOpacity(0.7)
                self._scene.addItem(self._rubber)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        press, self._press_scene = self._press_scene, None
        if self._rubber is not None:
            self._scene.removeItem(self._rubber)
            self._rubber = None
        if press is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        release = self.mapToScene(event.position().toPoint())
        if QLineF(press, release).length() <= TAP_THRESHOLD_PX:
            token = self._token_at(event.position().toPoint())
            if token is not None:
                self.player_tapped.emit(token.team_key, token.player_id)
            else:
                self.court_tapped.emit(release.x() / M, release.y() / M)
        else:
            self.trajectory_drawn.emit(press.x() / M, press.y() / M,
                                       release.x() / M, release.y() / M)
        super().mouseReleaseEvent(event)

    def _token_at(self, view_pos) -> PlayerToken | None:
        for item in self.items(view_pos):
            if isinstance(item, PlayerToken):
                return item
        return None

    # --------------------------------------------------------------- tokens

    def update_tokens(self, specs: list[dict]) -> None:
        """specs: dicts with keys team_key, player_id, number, name, color,
        badge, x, y (court metres), highlight, serving, acting_setter."""
        wanted = set()
        for s in specs:
            key = (s["team_key"], s["player_id"])
            wanted.add(key)
            token = self._tokens.get(key)
            if token is None:
                token = PlayerToken(*key)
                self._tokens[key] = token
                self._scene.addItem(token)
            token.set_appearance(s["number"], s["name"], s["color"],
                                 s.get("badge", ""), s.get("highlight", False),
                                 s.get("serving", False),
                                 s.get("acting_setter", False))
            token.setPos(s["x"] * M, s["y"] * M)
        for key in list(self._tokens):
            if key not in wanted:
                self._scene.removeItem(self._tokens.pop(key))

    # ------------------------------------------------------------ trajectories

    def clear_trajectories(self) -> None:
        self.cancel_trajectory_fade()
        for a in self._arrows:
            self._scene.removeItem(a)
        self._arrows.clear()

    def fade_out_trajectories(self) -> None:
        """The rally is over: keep the arrows briefly, then fade them away.
        Idempotent — a fade already pending or running keeps going."""
        if not self._arrows or self._fade_delay.isActive() or self._fade_anim:
            return
        self._fade_delay.start()

    def cancel_trajectory_fade(self) -> None:
        """Abort any pending/running fade (arrows are being rebuilt, e.g.
        after an undo, or the next serve is starting)."""
        self._fade_delay.stop()
        if self._fade_anim is not None:
            anim, self._fade_anim = self._fade_anim, None
            anim.stop()

    def _start_fade(self) -> None:
        targets = [(a, a.opacity()) for a in self._arrows]
        if not targets:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(FADE_DURATION_MS)
        anim.valueChanged.connect(lambda v: [
            a.setOpacity(base * float(v)) for a, base in targets])
        anim.finished.connect(self._finish_fade)
        self._fade_anim = anim
        anim.start()

    def _finish_fade(self) -> None:
        # cancel_trajectory_fade() also fires `finished` via stop(); it
        # nulls _fade_anim first, so only a natural finish clears arrows.
        if self._fade_anim is not None:
            self._fade_anim = None
            self.clear_trajectories()

    def add_trajectory(self, x1: float, y1: float, x2: float, y2: float,
                       kind: str = "attack", block_touch=None) -> None:
        for a in self._arrows:               # fade older arrows
            a.setOpacity(max(0.15, a.opacity() * 0.55))
        color = SERVE_ARROW if kind == "serve" else ATTACK_ARROW
        vertex = (QPointF(block_touch[0] * M, block_touch[1] * M)
                  if block_touch is not None else None)
        arrow = _Arrow(x1 * M, y1 * M, x2 * M, y2 * M, color, vertex=vertex)
        self._scene.addItem(arrow)
        self._arrows.append(arrow)
        if len(self._arrows) > 5:
            self._scene.removeItem(self._arrows.pop(0))

    def pop_last_trajectory(self) -> None:
        """Drop the most recently added arrow (used to swap a primed attack
        arrow for its two-segment blocked version)."""
        if self._arrows:
            self._scene.removeItem(self._arrows.pop())
