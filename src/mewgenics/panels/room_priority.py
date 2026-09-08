from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from save_parser import FurnitureRoomSummary
from mewgenics.constants import ROOM_COLORS, _room_color, _room_tint
from mewgenics.utils.localization import ROOM_DISPLAY, _tr
from mewgenics.utils.optimizer_settings import (
    _default_room_priority_config,
    _load_room_priority_config,
    _save_room_priority_config,
)
from mewgenics.utils.planner_state import ROOM_OPTIMIZER_MODES, _mutation_class_label


DEFAULT_MIN_COMFORT = 10
"""Comfort level rooms default to holding.

Comfort drives the overnight fight roll (about 16% chance of a fight at
Comfort 0 versus roughly 1% at Comfort 10), so rooms are sized to stay here
rather than being filled until Comfort reaches 0.
"""


class RoomPriorityPanel(QWidget):
    """Compact vertical panel for ordering rooms by optimizer mode."""
    configChanged = Signal()

    _SS_BTN = (
        "QPushButton { background:#1a1a32; color:#888; border:1px solid #2a2a4a;"
        " border-radius:3px; padding:2px 6px; font-size:11px; }"
        "QPushButton:hover { background:#252545; color:#ddd; }"
    )
    _SS_MODE = (
        "QComboBox { background:#1a1a32; color:#ddd; border:1px solid #2a2a4a;"
        " padding:2px 6px; font-size:11px; border-radius:3px; }"
        "QComboBox::drop-down { border:none; }"
        "QComboBox QAbstractItemView { background:#101023; color:#ddd;"
        " selection-background-color:#252545; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        header = QHBoxLayout()
        lbl = QLabel("Configure Rooms:")
        lbl.setStyleSheet("color:#888; font-size:11px; font-weight:bold;")
        lbl.setToolTip(_tr("room_priority.header.tooltip", default="Set each room's capacity and base stimulation level."))
        header.addWidget(lbl)
        header.addStretch(1)

        self._add_btn = QPushButton("+ Add Room")
        self._add_btn.setStyleSheet(self._SS_BTN)
        self._add_btn.clicked.connect(lambda: self._add_slot())
        header.addWidget(self._add_btn)
        outer.addLayout(header)

        self._fallback_note = QLabel("")
        self._fallback_note.setStyleSheet(
            "color:#caa56b; font-size:11px; font-style:italic;"
        )
        self._fallback_note.setWordWrap(True)
        outer.addWidget(self._fallback_note)

        self._slots: list[dict] = []
        self._room_stats: dict[str, FurnitureRoomSummary] = {}
        self._room_expected_pairs: dict[str, int] = {}
        self._available_rooms: list[str] = list(ROOM_DISPLAY.keys())
        self._save_path: Optional[str] = None
        self._slots_widget = QWidget()
        self._slots_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._slots_layout = QVBoxLayout(self._slots_widget)
        self._slots_layout.setContentsMargins(0, 0, 0, 0)
        self._slots_layout.setSpacing(4)
        self._slots_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._slots_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumHeight(0)
        scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QWidget#qt_scrollarea_viewport { background: transparent; }"
            "QScrollBar:vertical { width: 5px; background: #0d0d1a; }"
            "QScrollBar::handle:vertical { background: #2a2a4a; border-radius: 2px; }"
        )
        outer.addWidget(scroll, 1)

        self.set_config(_load_room_priority_config(self._save_path))

    def set_save_path(self, save_path: Optional[str]):
        self._save_path = save_path
        self.set_config(_load_room_priority_config(self._save_path))

    def reset_to_defaults(self):
        # Preserve the user's room priority configuration; nothing to reset.
        pass

    def _default_room_stim(self, room: str | None, fallback: float = 50.0) -> float:
        if room and room in self._room_stats:
            summary = self._room_stats.get(room)
            if summary is not None:
                return max(0.0, float(summary.raw_effects.get("Stimulation", 0.0) or 0.0))
        return float(fallback)

    def _room_choices(self) -> list[str]:
        choices = [room for room in ROOM_DISPLAY.keys() if room in set(self._available_rooms)]
        return choices or list(ROOM_DISPLAY.keys())

    def _room_limit(self) -> int:
        return len(self._room_choices())

    def _fallback_count(self) -> int:
        return sum(1 for slot in self._slots if slot["mode_combo"].currentData() == "fallback")

    def _refresh_fallback_feedback(self):
        fallback_count = self._fallback_count()
        if fallback_count <= 0:
            self._fallback_note.setText(
                "Best practice: keep at least one room as Fallback. Without one, calc times can increase significantly."
            )
            self._fallback_note.setStyleSheet(
                "color:#d28b5a; font-size:11px; font-style:italic;"
            )
        elif fallback_count == 1:
            self._fallback_note.setText(
                "Best practice: keep at least one room as Fallback. This setup can keep calc times lower."
            )
            self._fallback_note.setStyleSheet(
                "color:#caa56b; font-size:11px; font-style:italic;"
            )
        else:
            self._fallback_note.setText(
                "Best practice: keep at least one room as Fallback."
            )
            self._fallback_note.setStyleSheet(
                "color:#777; font-size:11px; font-style:italic;"
            )

    def _trim_excess_slots(self, *, persist: bool = False):
        """Drop any rows that exceed the current room limit."""
        limit = self._room_limit()
        if len(self._slots) <= limit:
            self._refresh_room_choices()
            return

        for slot in self._slots[limit:]:
            self._slots_layout.removeWidget(slot["widget"])
            slot["widget"].deleteLater()
        self._slots = self._slots[:limit]
        self._refresh_room_choices()
        if persist:
            self._on_changed()

    def _refresh_room_choices(self):
        """Keep each row's room combo unique across the panel."""
        if not self._slots:
            self._add_btn.setEnabled(len(self._slots) < self._room_limit())
            return

        current_rooms = [slot["combo"].currentData() for slot in self._slots]
        for slot in self._slots:
            current_room = slot["combo"].currentData()
            allowed_rooms = []
            for room in self._room_choices():
                if room == current_room or room not in current_rooms:
                    allowed_rooms.append(room)

            slot["combo"].blockSignals(True)
            slot["combo"].clear()
            for room in allowed_rooms:
                slot["combo"].addItem(ROOM_DISPLAY.get(room, room), room)
            idx = slot["combo"].findData(current_room)
            if idx < 0 and allowed_rooms:
                idx = 0
            if idx >= 0:
                slot["combo"].setCurrentIndex(idx)
            slot["combo"].blockSignals(False)

        self._add_btn.setEnabled(len(self._slots) < self._room_limit())
        self._refresh_fallback_feedback()

    def _update_expected_pairs_label(self, slot: dict):
        room = slot["combo"].currentData()
        expected = self._room_expected_pairs.get(room)
        slot["pairs_lbl"].setText(str(expected) if expected is not None else "—")

    def _clear_slots(self):
        for slot in list(self._slots):
            self._slots_layout.removeWidget(slot["widget"])
            slot["widget"].deleteLater()
        self._slots = []

    def _add_slot(
        self,
        room: str = None,
        slot_type: str = "best_pairs",
        emit: bool = True,
        max_cats: int | None = None,
        min_comfort: float | None = None,
        base_stim: float | None = None,
    ):
        choices = self._room_choices()
        if len(self._slots) >= len(choices):
            return
        used = {s["combo"].currentData() for s in self._slots}
        if room is None or room not in choices:
            room = next((k for k in choices if k not in used), next(iter(choices), None))
        if room is None:
            return

        w = QWidget()
        w.setAutoFillBackground(True)
        row = QHBoxLayout(w)
        row.setContentsMargins(3, 2, 3, 2)
        row.setSpacing(4)

        # Color swatch (thin accent bar on the left)
        swatch = QLabel()
        swatch.setFixedSize(6, 18)
        row.addWidget(swatch)

        combo = QComboBox()
        combo.setFixedWidth(82)
        combo.setStyleSheet(
            "QComboBox { background:#1a1a32; color:#ddd; border:1px solid #2a2a4a;"
            " padding:2px 4px; font-size:11px; border-radius:3px; }"
            "QComboBox::drop-down { border:none; }"
            "QComboBox QAbstractItemView { background:#101023; color:#ddd;"
            " selection-background-color:#252545; }"
        )
        for key in choices:
            disp = ROOM_DISPLAY.get(key, key)
            combo.addItem(disp, key)
        idx = combo.findData(room)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        row.addWidget(combo)

        mode_combo = QComboBox()
        mode_combo.setFixedWidth(100)
        mode_combo.setStyleSheet(self._SS_MODE)
        for mode in ROOM_OPTIMIZER_MODES:
            mode_combo.addItem(_mutation_class_label(mode), mode)
        idx = mode_combo.findData(slot_type if slot_type in ROOM_OPTIMIZER_MODES else "best_pairs")
        mode_combo.setCurrentIndex(idx if idx >= 0 else 0)
        row.addWidget(mode_combo)

        pairs_title = QLabel("Expected Pairs")
        pairs_title.setStyleSheet("color:#777; font-size:11px; font-weight:bold;")
        row.addWidget(pairs_title)

        pairs_lbl = QLabel("—")
        pairs_lbl.setFixedWidth(28)
        pairs_lbl.setAlignment(Qt.AlignCenter)
        pairs_lbl.setStyleSheet("color:#ddd; font-size:11px;")
        row.addWidget(pairs_lbl)

        cap_lbl = QLabel("Min Comfort")
        cap_lbl.setStyleSheet("color:#777; font-size:11px; font-weight:bold;")
        row.addWidget(cap_lbl)

        cap_spin = QSpinBox()
        cap_spin.setRange(-20, 50)
        cap_spin.setFixedWidth(66)
        cap_spin.setMinimumWidth(66)
        cap_spin.setStyleSheet(
            "QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:3px; padding:2px 4px; font-size:11px; }"
        )
        cap_spin.setToolTip(_tr(
            "room_priority.min_comfort.tooltip",
            default=(
                "Lowest room Comfort to allow, which sets how many cats fit.\n"
                "Comfort drops 1 per cat above 4 and drives the overnight "
                "fight roll:\nabout a 16% chance of a fight at Comfort 0 "
                "versus roughly 1% at Comfort 10.\n"
                "Fallback rooms ignore this — they take the overflow."
            ),
        ))
        if min_comfort is None:
            # Legacy configs stored a hand-computed capacity instead; there is
            # no way to recover the Comfort they were aiming for, so start
            # them at the default.
            min_comfort = DEFAULT_MIN_COMFORT
        try:
            cap_spin.setValue(int(round(float(min_comfort))))
        except (TypeError, ValueError):
            cap_spin.setValue(DEFAULT_MIN_COMFORT)
        row.addWidget(cap_spin)

        fit_lbl = QLabel("(fits: —)")
        fit_lbl.setStyleSheet("color:#5a607a; font-size:11px;")
        fit_lbl.setToolTip(_tr(
            "room_priority.fits.tooltip",
            default="How many cats this room holds at the chosen Min Comfort, based on its current furniture.",
        ))
        row.addWidget(fit_lbl)

        stim_lbl = QLabel("Stim")
        stim_lbl.setStyleSheet("color:#777; font-size:11px; font-weight:bold;")
        row.addWidget(stim_lbl)

        stim_spin = QSpinBox()
        stim_spin.setRange(0, 200)
        stim_spin.setFixedWidth(78)
        stim_spin.setMinimumWidth(78)
        stim_spin.setStyleSheet(
            "QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:3px; padding:2px 4px; font-size:11px; }"
        )
        stim_spin.setToolTip(_tr("room_priority.stim_override.tooltip", default="User override for the room's base stimulation. The calculated value is shown beside it."))
        stim_value = base_stim if base_stim is not None else self._default_room_stim(room)
        try:
            stim_spin.setValue(max(0, min(200, int(round(float(stim_value))))))
        except (TypeError, ValueError):
            stim_spin.setValue(max(0, min(200, int(round(self._default_room_stim(room))))))
        row.addWidget(stim_spin)

        calc_lbl = QLabel("(calc: —)")
        calc_lbl.setStyleSheet("color:#999; font-size:10px; font-style:italic;")
        calc_lbl.setToolTip(_tr("room_priority.calc_stim.tooltip", default="Calculated from the room's current furniture."))
        calc_lbl.setFixedWidth(82)
        row.addWidget(calc_lbl)

        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(22)
        up_btn.setStyleSheet(self._SS_BTN)
        up_btn.setToolTip(_tr("room_priority.move_up.tooltip", default="Move this room higher in priority."))
        row.addWidget(up_btn)

        dn_btn = QPushButton("↓")
        dn_btn.setFixedWidth(22)
        dn_btn.setStyleSheet(self._SS_BTN)
        dn_btn.setToolTip(_tr("room_priority.move_down.tooltip", default="Move this room lower in priority."))
        row.addWidget(dn_btn)

        rm_btn = QPushButton("×")
        rm_btn.setFixedWidth(20)
        rm_btn.setStyleSheet(
            "QPushButton { background:#3a1a1a; color:#e08080; border:1px solid #5a2a2a;"
            " border-radius:3px; font-size:11px; }"
            "QPushButton:hover { background:#5a2a2a; }"
        )
        rm_btn.setToolTip(_tr("room_priority.remove.tooltip", default="Remove this room from the priority list."))
        row.addWidget(rm_btn)
        row.addStretch(1)

        slot = {
            "combo": combo,
            "mode_combo": mode_combo,
            "pairs_lbl": pairs_lbl,
            "cap_spin": cap_spin,
            "fit_lbl": fit_lbl,
            "stim_spin": stim_spin,
            "calc_lbl": calc_lbl,
            "up_btn": up_btn,
            "dn_btn": dn_btn,
            "rm_btn": rm_btn,
            "widget": w,
            "swatch": swatch,
        }
        self._slots.append(slot)
        self._slots_layout.insertWidget(self._slots_layout.count() - 1, w)

        def _update_swatch(_s=slot):
            key = _s["combo"].currentData()
            color = _room_color(key)
            r, g, b = color.red(), color.green(), color.blue()
            # Thin swatch bar: full color
            _s["swatch"].setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border-radius: 2px;"
            )
            # Box background: heavily dimmed tint
            tint = _room_tint(key)
            _s["widget"].setStyleSheet(
                f"QWidget {{ background-color: rgb({tint.red()},{tint.green()},{tint.blue()});"
                " border-radius: 4px; }"
            )

        def _on_mode_changed(_index, _s=slot):
            selected_mode = _s["mode_combo"].currentData()
            # Fallback rooms ignore Min Comfort (they absorb the overflow),
            # so there is nothing to switch when the mode changes.
            self._refresh_fallback_feedback()
            self.refresh_fit_labels()
            self._on_changed()

        mode_combo.currentIndexChanged.connect(_on_mode_changed)
        combo.currentIndexChanged.connect(lambda _: (_update_swatch(), self._update_expected_pairs_label(slot), self._refresh_room_choices(), self.refresh_fit_labels(), self._on_changed()))
        cap_spin.valueChanged.connect(lambda _, _s=None: (self.refresh_fit_labels(), self._on_changed()))
        stim_spin.valueChanged.connect(lambda _: self._on_changed())
        up_btn.clicked.connect(lambda checked=False, _s=slot: self._move(-1, _s))
        dn_btn.clicked.connect(lambda checked=False, _s=slot: self._move(+1, _s))
        rm_btn.clicked.connect(lambda checked=False, _s=slot: self._remove(_s))

        _update_swatch()
        self._update_expected_pairs_label(slot)
        self._refresh_room_choices()

        if emit:
            self._on_changed()

    def _move(self, direction: int, slot: dict):
        if slot not in self._slots:
            return
        i = self._slots.index(slot)
        j = i + direction
        if not (0 <= j < len(self._slots)):
            return
        a, b = self._slots[i], self._slots[j]
        a_room, b_room = a["combo"].currentData(), b["combo"].currentData()
        a_mode, b_mode = a["mode_combo"].currentData(), b["mode_combo"].currentData()
        a_cap, b_cap = a["cap_spin"].value(), b["cap_spin"].value()
        a_stim, b_stim = a["stim_spin"].value(), b["stim_spin"].value()
        a_calc, b_calc = a["calc_lbl"].text(), b["calc_lbl"].text()
        for s in (a, b):
            s["combo"].blockSignals(True)
            s["mode_combo"].blockSignals(True)
            s["cap_spin"].blockSignals(True)
            s["stim_spin"].blockSignals(True)
        a["combo"].setCurrentIndex(a["combo"].findData(b_room))
        b["combo"].setCurrentIndex(b["combo"].findData(a_room))
        a["mode_combo"].setCurrentIndex(a["mode_combo"].findData(b_mode))
        b["mode_combo"].setCurrentIndex(b["mode_combo"].findData(a_mode))
        a["cap_spin"].setValue(b_cap)
        b["cap_spin"].setValue(a_cap)
        a["stim_spin"].setValue(b_stim)
        b["stim_spin"].setValue(a_stim)
        a["calc_lbl"].setText(b_calc)
        b["calc_lbl"].setText(a_calc)
        for s in (a, b):
            s["combo"].blockSignals(False)
            s["mode_combo"].blockSignals(False)
            s["cap_spin"].blockSignals(False)
            s["stim_spin"].blockSignals(False)
            key = s["combo"].currentData()
            color = ROOM_COLORS.get(key, QColor(80, 80, 100))
            r, g, b = color.red(), color.green(), color.blue()
            s["swatch"].setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border-radius: 2px;"
            )
            s["widget"].setStyleSheet(
                f"QWidget {{ background-color: rgb({max(18,r//5)},{max(18,g//5)},{max(18,b//5)});"
                " border-radius: 4px; }"
            )
            self._update_expected_pairs_label(s)
        self._refresh_room_choices()
        self._on_changed()

    def _remove(self, slot: dict):
        if slot not in self._slots:
            return
        self._slots.remove(slot)
        self._slots_layout.removeWidget(slot["widget"])
        slot["widget"].deleteLater()
        self._refresh_room_choices()
        self._refresh_fallback_feedback()
        self._on_changed()

    def _on_changed(self, *, persist: bool = True):
        if persist:
            _save_room_priority_config(self.get_config(), self._save_path)
        self.configChanged.emit()

    def _refresh_fit_label(self, slot: dict, summary=None):
        """Show how many cats the room holds at the chosen Min Comfort."""
        fit_lbl = slot.get("fit_lbl")
        if fit_lbl is None:
            return
        room = slot["combo"].currentData()
        if summary is None:
            summary = self._room_stats.get(room)
        mode = slot["mode_combo"].currentData() or "best_pairs"
        if mode == "fallback":
            fit_lbl.setText("(fits: ∞)")
            fit_lbl.setToolTip(_tr(
                "room_priority.fits_fallback.tooltip",
                default="Fallback rooms take the overflow, so they are not limited by Comfort.",
            ))
            return
        if summary is None:
            fit_lbl.setText("(fits: —)")
            return
        from room_optimizer.optimizer import comfort_capped_occupancy
        try:
            comfort = float(summary.raw_effects.get("Comfort", 0.0) or 0.0)
        except (TypeError, ValueError):
            comfort = 0.0
        target = float(slot["cap_spin"].value())
        fits = comfort_capped_occupancy(comfort, target)
        fit_lbl.setText(f"(fits: {fits})")
        reachable = comfort - max(0, fits - 4) >= target
        if reachable:
            fit_lbl.setToolTip(_tr(
                "room_priority.fits_value.tooltip",
                default="Room Comfort is {comfort:g}; {fits} cats keeps it at {target:g}.",
                comfort=comfort, fits=fits, target=target,
            ))
        else:
            fit_lbl.setToolTip(_tr(
                "room_priority.fits_unreachable.tooltip",
                default=(
                    "Room Comfort is only {comfort:g}, so it cannot reach {target:g} "
                    "at any occupancy. Showing the 4 cats that cost no Comfort — "
                    "add Comfort furniture to fit more."
                ),
                comfort=comfort, target=target,
            ))

    def refresh_fit_labels(self):
        for slot in self._slots:
            self._refresh_fit_label(slot)

    def get_config(self) -> list[dict]:
        return [
            {
                "room": s["combo"].currentData(),
                "type": s["mode_combo"].currentData() or "best_pairs",
                "min_comfort": int(s["cap_spin"].value()),
                "base_stim": float(s["stim_spin"].value()),
            }
            for s in self._slots
        ]

    def set_config(self, config: list[dict]):
        self._clear_slots()
        for slot in config:
            self._add_slot(
                slot.get("room"),
                slot.get("type", "best_pairs"),
                emit=False,
                max_cats=slot.get("max_cats", slot.get("capacity")),
                min_comfort=slot.get("min_comfort"),
                base_stim=slot.get("base_stim", slot.get("stimulation")),
            )
        self._trim_excess_slots()
        self._refresh_fallback_feedback()

    def set_available_rooms(self, rooms: list[str]):
        ordered = [room for room in ROOM_DISPLAY.keys() if room in set(rooms or [])]
        self._available_rooms = ordered or list(ROOM_DISPLAY.keys())
        current = self.get_config()
        max_slots = self._room_limit()
        normalized: list[dict] = []
        for slot in current[:max_slots]:
            room = slot.get("room")
            if room not in self._available_rooms:
                room = self._available_rooms[0] if self._available_rooms else None
            if room is None:
                continue
            updated = dict(slot)
            updated["room"] = room
            normalized.append(updated)
        self.set_config(normalized)
        self._trim_excess_slots(persist=True)

    def set_room_summaries(self, summaries: list[FurnitureRoomSummary] | dict[str, FurnitureRoomSummary]):
        if isinstance(summaries, dict):
            room_map = {
                room: summary
                for room, summary in summaries.items()
                if room and isinstance(summary, FurnitureRoomSummary)
            }
        else:
            room_map = {
                summary.room: summary
                for summary in summaries
                if isinstance(summary, FurnitureRoomSummary) and summary.room
            }
        self._room_stats = room_map

        if not self._slots:
            self.configChanged.emit()
            return

        for slot in self._slots:
            room = slot["combo"].currentData()
            summary = room_map.get(room)
            if summary is None:
                slot["calc_lbl"].setText("(calc: —)")
                slot["calc_lbl"].setToolTip(_tr("room_priority.calc_stim.tooltip", default="Calculated from the room's current furniture."))
                slot["fit_lbl"].setText("(fits: —)")
                continue
            stim = max(0, min(200, int(round(float(summary.raw_effects.get("Stimulation", 0.0) or 0.0)))))
            slot["calc_lbl"].setText(f"(calc: {stim})")
            slot["calc_lbl"].setToolTip(
                _tr("room_priority.calc_stim_value.tooltip", default="Calculated stimulation from furniture: {stim}", stim=stim)
            )
            self._refresh_fit_label(slot, summary)

        self.configChanged.emit()

    def set_room_expected_pairs(self, room_rows: list[dict] | dict[str, int]):
        if isinstance(room_rows, dict):
            self._room_expected_pairs = {
                room: int(count)
                for room, count in room_rows.items()
                if room in ROOM_DISPLAY and isinstance(count, (int, float))
            }
        else:
            self._room_expected_pairs = {
                row.get("room"): int(row.get("pairs", []).__len__()) if isinstance(row, dict) else 0
                for row in room_rows
                if isinstance(row, dict) and row.get("room") in ROOM_DISPLAY
            }
        for slot in self._slots:
            self._update_expected_pairs_label(slot)
