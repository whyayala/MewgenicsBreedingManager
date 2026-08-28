"""Mutation & Disorder Breeding Planner view and helper functions."""

import re
from collections import Counter
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QSpinBox, QPushButton,
    QSplitter, QFrame, QScrollArea,
    QTableWidget, QTableWidgetItem, QToolButton,
    QAbstractItemView, QHeaderView, QDialog,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor

from save_parser import (
    Cat, STAT_NAMES, can_breed, risk_percent, kinship_coi,
    _stimulation_inheritance_weight, _defect_inheritance_weight,
    _inheritance_candidates, _malady_breakdown, is_basic_attack_token,
)

from mewgenics.utils.localization import _tr, ROOM_DISPLAY
from mewgenics.utils.abilities import (
    _mutation_display_name, _ability_tip, _ability_family_tip, _strip_tier,
    _cat_has_trait, _planner_trait_display_name,
    _trait_selector_summary, _trait_selector_label,
    _trait_display_kind, _trait_visible_detail,
    _planner_trait_name_html, _planner_trait_name_palette,
    _planner_trait_weight,
)
from mewgenics.utils.cat_analysis import _cat_uid
from mewgenics.utils.tags import _cat_tags, _make_tag_icon
from mewgenics.utils.planner_state import (
    DEFAULT_MUTATION_CLASS_STAT_PRIORITY,
    MUTATION_CLASS_MODES,
    _default_mutation_mode_profiles,
    _load_planner_state_value,
    _mutation_class_label,
    _normalize_mutation_traits,
    _normalize_mutation_mode_profiles,
    _normalize_stat_priority,
    _save_planner_state_value,
)
from mewgenics.utils.styling import _blend_qcolor
from mewgenics.models.cat_table_model import _SortByUserRoleItem


def _planner_trait_color(ratio: float) -> QColor:
    """Return a tint color for mutation-planner trait coverage."""
    ratio = max(-1.0, min(1.0, float(ratio)))
    neutral = QColor(29, 29, 44)
    positive_low = QColor(214, 163, 69)
    positive_high = QColor(82, 185, 146)
    negative = QColor(177, 84, 94)
    if ratio > 0:
        warm = _blend_qcolor(positive_low, positive_high, min(ratio, 1.0))
        return _blend_qcolor(neutral, warm, 0.28 + 0.58 * min(ratio, 1.0))
    if ratio < 0:
        return _blend_qcolor(neutral, negative, 0.36 + 0.54 * min(abs(ratio), 1.0))
    return neutral


def _planner_trait_style(ratio: float, *, alpha: int = 150) -> str:
    color = _planner_trait_color(ratio)
    color.setAlpha(max(0, min(255, int(alpha))))
    border = QColor(color).lighter(135)
    border.setAlpha(max(0, min(255, int(alpha + 40))))
    return (
        f"background-color: rgba({color.red()},{color.green()},{color.blue()},{color.alpha()});"
        f"color:#fff; border:1px solid rgba({border.red()},{border.green()},{border.blue()},{border.alpha()});"
        "border-radius:3px; padding:1px 4px;"
    )


def _planner_trait_name_colors(weight: float) -> tuple[QColor, Optional[QColor]]:
    fg_hex, bg_hex, _border_hex = _planner_trait_name_palette(weight)
    fg = QColor(fg_hex)
    bg = QColor(bg_hex) if bg_hex else None
    return fg, bg


def _planner_trait_tooltip(summary: dict, *, label: str = "Mutation planner") -> str:
    if not summary:
        return ""

    score = float(summary.get("score", 0.0))
    matches = list(summary.get("matches", []) or [])
    penalties = list(summary.get("penalties", []) or [])
    parts = [f"{label}: {score:+.1f}"]
    if matches:
        parts.append("Matches: " + ", ".join(matches[:4]) + ("..." if len(matches) > 4 else ""))
    if penalties:
        parts.append("Penalties: " + ", ".join(penalties[:4]) + ("..." if len(penalties) > 4 else ""))
    return "\n".join(parts)


def _planner_trait_summary_for_cat(cat: 'Cat', traits: Sequence[dict]) -> dict:
    positive_score = 0.0
    negative_score = 0.0
    max_score = 0.0
    matches: list[str] = []
    penalties: list[str] = []

    for trait in traits:
        category = str(trait.get("category", "")).strip()
        key = str(trait.get("key", "")).strip().lower()
        if not category or not key:
            continue

        weight = float(trait.get("weight", 0) or 0)
        if weight == 0:
            continue

        max_score += abs(weight)
        if not _cat_has_trait(cat, category, key):
            continue

        display = _planner_trait_display_name(str(trait.get("display") or key))
        if weight > 0:
            matches.append(display)
            positive_score += weight
        else:
            penalties.append(display)
            negative_score += abs(weight)

    net_score = positive_score - negative_score
    ratio = net_score / max(1.0, max_score)
    return {
        "score": net_score,
        "ratio": ratio,
        "positive": positive_score,
        "negative": negative_score,
        "matches": matches,
        "penalties": penalties,
        "max": max_score,
    }


def _planner_trait_summary_for_pair(cat_a: 'Cat', cat_b: 'Cat', traits: Sequence[dict]) -> dict:
    score = 0.0
    max_score = 0.0
    matches: list[str] = []
    penalties: list[str] = []

    for trait in traits:
        category = str(trait.get("category", "")).strip()
        key = str(trait.get("key", "")).strip().lower()
        if not category or not key:
            continue

        weight = float(trait.get("weight", 0) or 0)
        if weight == 0:
            continue

        scale = weight / 10.0
        max_score += abs(scale) * 7.5

        a_has = _cat_has_trait(cat_a, category, key)
        b_has = _cat_has_trait(cat_b, category, key)
        if not (a_has or b_has):
            continue

        display = _planner_trait_display_name(str(trait.get("display") or key))
        if weight > 0:
            matches.append(display)
        else:
            penalties.append(display)

        score += scale * 5.0
        if a_has and b_has:
            score += scale * 2.5

    ratio = score / max(1.0, max_score)
    return {
        "score": score,
        "ratio": ratio,
        "matches": matches,
        "penalties": penalties,
        "max": max_score,
    }


class _MutationClassSummaryDialog(QDialog):
    def __init__(self, mode_profiles: dict[str, dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mutation Trees")
        self.resize(520, 520)
        self.setStyleSheet(
            "QDialog { background:#0a0a18; color:#ddd; }"
            "QLabel { color:#bbb; }"
            "QFrame { background:#101023; border:1px solid #26264a; border-radius:6px; }"
            "QPushButton { background:#1a1a32; color:#ddd; border:1px solid #2a2a4a; border-radius:4px; padding:6px 10px; }"
            "QPushButton:hover { background:#252545; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("Mutation Trees")
        title.setStyleSheet("color:#ddd; font-size:16px; font-weight:bold;")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        for mode in MUTATION_CLASS_MODES:
            profile = mode_profiles.get(mode, {})
            traits = list(profile.get("traits", []) or [])

            card = QFrame()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(4)

            header = QLabel(_mutation_class_label(mode))
            header.setStyleSheet("color:#8fb8a0; font-size:13px; font-weight:bold;")
            card_layout.addWidget(header)

            if traits:
                trait_lines = ", ".join(
                    f"{_planner_trait_name_html(trait.get('display', trait.get('key', '?')), trait.get('weight', 0))} "
                    f"<span style=\"color:#9aa6ba;\">({int(trait.get('weight', 0) or 0):+d})</span>"
                    for trait in traits
                )
            else:
                trait_lines = "No mutation traits selected."
            trait_label = QLabel(trait_lines)
            trait_label.setTextFormat(Qt.RichText)
            trait_label.setWordWrap(True)
            trait_label.setStyleSheet("color:#aaa; font-size:11px;")
            card_layout.addWidget(trait_label)
            body_layout.addWidget(card)

        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignRight)


class MutationDisorderPlannerView(QWidget):
    """View for planning breeding around specific mutations, disorders, and passives."""

    traitsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QWidget { background:#0a0a18; }"
            "QLabel { color:#bbb; }"
            "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; }"
            "QHeaderView::section { background:#151532; color:#7d8bb0; border:none; padding:4px; font-weight:bold; }"
            "QPushButton { background:#1a1a32; color:#aaa; border:1px solid #2a2a4a; "
            "border-radius:4px; padding:6px 12px; font-size:11px; }"
            "QPushButton:hover { background:#252545; color:#ddd; }"
        )
        self._cats: list[Cat] = []
        self._alive_cats: list[Cat] = []
        self._selected_pair: list[Cat] = []
        self._selected_mode = "best_pairs"
        self._mode_profiles: dict[str, dict] = _default_mutation_mode_profiles()
        self._selected_traits: list[dict] = self._mode_profiles[self._selected_mode]["traits"]  # active profile alias
        self._active_trait_data: tuple[str, str] | None = None
        self._browse_trait_datas: list[tuple[str, str]] = []
        self._trait_catalog: list[dict] = []
        self._navigate_to_cat_callback = None
        self._save_path: Optional[str] = None
        self._session_state: dict = _load_planner_state_value("mutation_planner_state", {})
        self._restoring_session_state = False
        self._suppress_traits_changed = False
        self._syncing_trait_selection = False
        self._build_ui()

    def _notify_traits_changed(self):
        if getattr(self, "_suppress_traits_changed", False):
            return
        self.traitsChanged.emit()

    def _active_mode_profile(self) -> dict:
        profile = self._mode_profiles.get(self._selected_mode)
        if not isinstance(profile, dict):
            self._mode_profiles[self._selected_mode] = {
                "traits": [],
                "stat_priority": list(DEFAULT_MUTATION_CLASS_STAT_PRIORITY.get(self._selected_mode, STAT_NAMES)),
            }
            profile = self._mode_profiles[self._selected_mode]
        profile.setdefault("traits", [])
        profile.setdefault("stat_priority", list(DEFAULT_MUTATION_CLASS_STAT_PRIORITY.get(self._selected_mode, STAT_NAMES)))
        return profile

    def _sync_selected_traits_reference(self):
        self._selected_traits = self._active_mode_profile()["traits"]

    def _active_stat_priority(self) -> list[str]:
        profile = self._active_mode_profile()
        profile["stat_priority"] = _normalize_stat_priority(profile.get("stat_priority", []), fallback_mode=self._selected_mode)
        return profile["stat_priority"]

    def _set_active_stat_priority(self, order: Sequence[str]):
        self._active_mode_profile()["stat_priority"] = _normalize_stat_priority(order, fallback_mode=self._selected_mode)

    def _set_active_mode_traits(self, traits) -> list[dict]:
        profile = self._active_mode_profile()
        profile["traits"] = _normalize_mutation_traits(traits)
        self._sync_selected_traits_reference()
        self._refresh_selected_traits_metadata(active_only=True)
        return self._selected_traits

    def get_selected_mode(self) -> str:
        return self._selected_mode

    def get_mode_profiles(self) -> dict[str, dict]:
        profiles = _normalize_mutation_mode_profiles(self._mode_profiles, legacy_traits=self._selected_traits)
        has_traits = any(profiles.get(mode, {}).get("traits") for mode in MUTATION_CLASS_MODES)
        if has_traits:
            return profiles
        state = self._session_state if isinstance(self._session_state, dict) else {}
        return _normalize_mutation_mode_profiles(
            state.get("mode_profiles", {}),
            legacy_traits=state.get("selected_traits", []),
        )

    def get_traits_for_mode(self, mode: str) -> list[dict]:
        profiles = self.get_mode_profiles()
        return [dict(t) for t in profiles.get(str(mode or "").strip().lower(), {}).get("traits", [])]

    def get_stat_priority_for_mode(self, mode: str) -> list[str]:
        profiles = self.get_mode_profiles()
        return list(profiles.get(str(mode or "").strip().lower(), {}).get("stat_priority", []))

    def set_stat_priority_for_mode(self, mode: str, order: Sequence[str], *, save: bool = True, notify: bool = True):
        mode_key = str(mode or "").strip().lower()
        if mode_key not in MUTATION_CLASS_MODES:
            return
        profile = self._mode_profiles.setdefault(mode_key, {
            "traits": [],
            "stat_priority": list(DEFAULT_MUTATION_CLASS_STAT_PRIORITY.get(mode_key, STAT_NAMES)),
        })
        profile["stat_priority"] = _normalize_stat_priority(order, fallback_mode=mode_key)
        if save:
            self._save_session_state()
        if notify:
            self._notify_traits_changed()

    def _trait_catalog_entry(self, category: str, key: str) -> Optional[dict]:
        category = str(category or "").strip()
        key = str(key or "").strip().lower()
        return next(
            (
                row for row in self._trait_catalog
                if row.get("category") == category and row.get("key") == key
            ),
            None,
        )

    def _decorate_selected_trait(self, trait: dict) -> dict:
        category = str(trait.get("category") or "").strip()
        key = str(trait.get("key") or "").strip().lower()
        row_data = self._trait_catalog_entry(category, key)
        try:
            weight = int(trait.get("weight", 5))
        except (TypeError, ValueError):
            weight = 5
        decorated = {
            "category": category,
            "key": key,
            "display": str(trait.get("display") or key).strip() or key,
            "weight": weight,
        }
        if row_data is not None:
            decorated.update({
                "display": row_data.get("display") or decorated["display"],
                "tip": str(row_data.get("tip") or trait.get("tip") or ""),
                "desc": str(row_data.get("desc") or trait.get("desc") or ""),
                "stats": str(row_data.get("stats") or trait.get("stats") or ""),
                "kind": str(row_data.get("kind") or trait.get("kind") or ""),
                "cats": int(row_data.get("cats", trait.get("cats", 0)) or 0),
            })
        else:
            decorated.update({
                "tip": str(trait.get("tip") or ""),
                "desc": str(trait.get("desc") or ""),
                "stats": str(trait.get("stats") or ""),
                "kind": str(trait.get("kind") or ""),
                "cats": int(trait.get("cats", 0) or 0),
            })
        return decorated

    def _refresh_selected_traits_metadata(self, *, active_only: bool = False):
        target_modes = [self._selected_mode] if active_only else list(MUTATION_CLASS_MODES)
        for mode in target_modes:
            profile = self._mode_profiles.get(mode)
            if not isinstance(profile, dict):
                continue
            profile["traits"] = [self._decorate_selected_trait(trait) for trait in profile.get("traits", []) if isinstance(trait, dict)]
        self._sync_selected_traits_reference()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(4)

        # Header
        header = QHBoxLayout()
        self._title = QLabel(_tr("mutation_planner.title"))
        self._title.setStyleSheet("color:#ddd; font-size:18px; font-weight:bold;")
        header.addWidget(self._title)
        self._mode_label = QLabel("Tree:")
        self._mode_label.setStyleSheet("color:#888; font-size:11px;")
        header.addWidget(self._mode_label)
        self._mode_combo = QComboBox()
        self._mode_combo.setFixedWidth(130)
        self._mode_combo.setStyleSheet(
            "QComboBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
        )
        for mode in MUTATION_CLASS_MODES:
            self._mode_combo.addItem(_mutation_class_label(mode), mode)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        header.addWidget(self._mode_combo)
        self._show_tree_summary_btn = QPushButton("View Trees")
        self._show_tree_summary_btn.setFixedWidth(95)
        self._show_tree_summary_btn.clicked.connect(self._open_tree_summary_dialog)
        header.addWidget(self._show_tree_summary_btn)
        header.addStretch()
        root.addLayout(header)

        # Controls row
        controls = QHBoxLayout()
        controls.setSpacing(6)
        self._room_label = QLabel(_tr("mutation_planner.room"))
        self._room_combo = QComboBox()
        self._room_combo.setFixedWidth(200)
        self._room_combo.setStyleSheet(
            "QComboBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
        )
        self._room_combo.currentIndexChanged.connect(self._refresh_table)
        self._room_combo.currentIndexChanged.connect(lambda _: self._save_session_state())
        controls.addStretch()
        self._pair_label = QLabel(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        controls.addWidget(self._pair_label)
        root.addLayout(controls)

        # Target trait row
        trait_row = QHBoxLayout()
        trait_row.setSpacing(6)
        self._target_trait_label = QLabel(_tr("mutation_planner.target_trait"))
        trait_row.addWidget(self._target_trait_label)
        self._trait_search = QLineEdit()
        self._trait_search.setPlaceholderText(_tr("mutation_planner.search_placeholder"))
        self._trait_search.setFixedWidth(160)
        self._trait_search.setClearButtonEnabled(True)
        self._trait_search.setStyleSheet(
            "QLineEdit { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
        )
        self._trait_search.textChanged.connect(self._on_trait_search_changed)
        self._trait_search.textChanged.connect(lambda _: self._save_session_state())
        trait_row.addWidget(self._trait_search)
        self._trait_combo = QComboBox()
        self._trait_combo.setFixedWidth(300)
        self._trait_combo.setStyleSheet(
            "QComboBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
        )
        self._trait_combo.currentIndexChanged.connect(self._on_target_trait_changed)
        self._trait_combo.currentIndexChanged.connect(lambda _: self._save_session_state())
        trait_row.addWidget(self._trait_combo)
        self._trait_combo.setVisible(False)
        self._stimulation_label = QLabel(_tr("mutation_planner.stimulation"))
        trait_row.addWidget(self._stimulation_label)
        self._stim_spin = QSpinBox()
        self._stim_spin.setRange(0, 100)
        self._stim_spin.setValue(10)
        self._stim_spin.setFixedWidth(60)
        self._stim_spin.setStyleSheet(
            "QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px; }"
        )
        self._stim_spin.valueChanged.connect(self._on_stim_changed)
        self._stim_spin.valueChanged.connect(lambda _: self._save_session_state())
        trait_row.addWidget(self._stim_spin)
        # "Add" button to add selected trait to the multi-select list
        self._deselect_traits_btn = QPushButton(_tr("mutation_planner.deselect_traits", default="Deselect"))
        self._deselect_traits_btn.setFixedWidth(90)
        self._deselect_traits_btn.setStyleSheet(
            "QPushButton { background:#2a2a1a; color:#cc8; border:1px solid #4a4a2a; "
            "border-radius:4px; padding:4px 8px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#3a3a2a; }"
        )
        self._deselect_traits_btn.clicked.connect(self._on_deselect_traits)
        trait_row.addWidget(self._deselect_traits_btn)
        self._add_trait_btn = QPushButton(_tr("mutation_planner.add_trait", default="Add Desired"))
        self._add_trait_btn.setFixedWidth(120)
        self._add_trait_btn.setStyleSheet(
            "QPushButton { background:#1f5f4a; color:#f2f7f3; border:1px solid #3f8f72; "
            "border-radius:4px; padding:4px 8px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#26735a; }"
        )
        self._add_trait_btn.clicked.connect(self._on_add_trait)
        trait_row.addWidget(self._add_trait_btn)
        self._add_trait_btn.setVisible(True)
        self._add_undesired_btn = QPushButton(_tr("mutation_planner.add_undesired", default="Add Undesired"))
        self._add_undesired_btn.setFixedWidth(120)
        self._add_undesired_btn.setStyleSheet(
            "QPushButton { background:#4a1a2a; color:#e8a0a0; border:1px solid #6a2a3a; "
            "border-radius:4px; padding:4px 8px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#5a2a3a; }"
        )
        self._add_undesired_btn.clicked.connect(self._on_add_undesired_trait)
        trait_row.addWidget(self._add_undesired_btn)
        self._remove_trait_btn = QPushButton(_tr("mutation_planner.remove_selected_trait", default="Remove Trait"))
        self._remove_trait_btn.setFixedWidth(120)
        self._remove_trait_btn.setStyleSheet(
            "QPushButton { background:#2a1a1a; color:#c88; border:1px solid #4a2a2a; "
            "border-radius:4px; padding:4px 8px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#3a2a2a; }"
        )
        self._remove_trait_btn.clicked.connect(self._on_remove_selected_trait)
        trait_row.addWidget(self._remove_trait_btn)
        # Master list of (display_text, user_data) for filtering
        self._trait_items_master: list[tuple[str, object]] = []
        self._trait_info_label = QLabel("")
        self._trait_info_label.setStyleSheet("color:#666; font-size:11px;")
        trait_row.addWidget(self._trait_info_label)
        self._trait_info_label.setVisible(False)
        trait_row.addStretch()
        root.addLayout(trait_row)

        # Main splitter: trait browser left, cat list + outcome panel right
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mutation_planner_main_splitter")
        splitter.setStyleSheet("QSplitter::handle { background:#26264a; width:3px; }")
        self._splitter = splitter

        # Left: trait browser
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        trait_detail = QFrame()
        trait_detail.setStyleSheet("QFrame { background:#0e0e20; border:1px solid #26264a; border-radius:4px; }")
        trait_detail_layout = QVBoxLayout(trait_detail)
        trait_detail_layout.setContentsMargins(8, 6, 8, 6)
        trait_detail_layout.setSpacing(3)
        self._trait_detail_title = QLabel(_tr("mutation_planner.target_trait"))
        self._trait_detail_title.setStyleSheet("color:#8fb8a0; font-size:12px; font-weight:bold;")
        trait_detail_layout.addWidget(self._trait_detail_title)
        self._trait_detail_meta = QLabel("")
        self._trait_detail_meta.setStyleSheet("color:#bbb; font-size:11px;")
        self._trait_detail_meta.setWordWrap(True)
        trait_detail_layout.addWidget(self._trait_detail_meta)
        self._trait_detail_desc = QLabel(_tr("mutation_planner.no_traits_selected"))
        self._trait_detail_desc.setStyleSheet("color:#888; font-size:11px;")
        self._trait_detail_desc.setWordWrap(True)
        trait_detail_layout.addWidget(self._trait_detail_desc)
        left_layout.addWidget(trait_detail)
        trait_detail.setVisible(False)

        self._trait_table = QTableWidget(0, 5)
        self._trait_table.setHorizontalHeaderLabels([
            "Sel",
            "Trait",
            "Type",
            "Cats",
            "Description",
        ])
        self._trait_table.verticalHeader().setVisible(False)
        self._trait_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._trait_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._trait_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._trait_table.setSortingEnabled(True)
        self._trait_table.setAlternatingRowColors(True)
        thh = self._trait_table.horizontalHeader()
        thh.setSectionResizeMode(0, QHeaderView.Fixed)
        thh.setSectionResizeMode(1, QHeaderView.Interactive)
        thh.setSectionResizeMode(2, QHeaderView.Interactive)
        thh.setSectionResizeMode(3, QHeaderView.Fixed)
        thh.setSectionResizeMode(4, QHeaderView.Stretch)
        self._trait_table.setColumnWidth(0, 30)
        self._trait_table.setColumnWidth(1, 160)
        self._trait_table.setColumnWidth(2, 120)
        self._trait_table.setColumnWidth(3, 45)
        self._trait_table.sortByColumn(2, Qt.AscendingOrder)
        self._trait_table.selectionModel().selectionChanged.connect(self._on_trait_table_selection_changed)
        left_layout.addWidget(self._trait_table)
        splitter.addWidget(left)

        # Right: room selector header + vertical splitter with cat list (top),
        # selected traits (middle), outcome (bottom)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(2)
        right_header = QHBoxLayout()
        right_header.setSpacing(6)
        right_header.addWidget(self._room_label)
        right_header.addWidget(self._room_combo)
        right_header.addStretch()
        right_layout.addLayout(right_header)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.setObjectName("mutation_planner_right_splitter")
        right_splitter.setStyleSheet("QSplitter::handle { background:#26264a; height:3px; }")
        self._right_splitter = right_splitter

        # -- Cat table --
        self._cat_table = QTableWidget(0, 7)
        self._cat_table.setIconSize(QSize(60, 20))
        self._cat_table.setHorizontalHeaderLabels([
            _tr("mutation_planner.table.name"),
            _tr("mutation_planner.table.gender"),
            _tr("mutation_planner.table.age"),
            _tr("mutation_planner.table.sum"),
            _tr("mutation_planner.table.mutations"),
            _tr("mutation_planner.table.passives_disorders"),
            _tr("mutation_planner.table.abilities"),
        ])
        self._cat_table.verticalHeader().setVisible(False)
        self._cat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cat_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._cat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cat_table.setSortingEnabled(True)
        self._cat_table.setAlternatingRowColors(True)
        hh = self._cat_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        hh.setSectionResizeMode(3, QHeaderView.Interactive)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Stretch)
        hh.setSectionResizeMode(6, QHeaderView.Stretch)
        self._cat_table.setColumnWidth(0, 130)
        self._cat_table.setColumnWidth(1, 50)
        self._cat_table.setColumnWidth(2, 40)
        self._cat_table.setColumnWidth(3, 50)
        self._cat_table.sortByColumn(0, Qt.AscendingOrder)
        self._cat_table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        right_splitter.addWidget(self._cat_table)

        # -- Selected traits panel --
        traits_panel = QWidget()
        self._traits_panel = traits_panel
        traits_panel.setStyleSheet("QWidget { background:#0e0e20; }")
        traits_panel_layout = QVBoxLayout(traits_panel)
        traits_panel_layout.setContentsMargins(6, 4, 6, 4)
        traits_panel_layout.setSpacing(3)
        traits_header = QHBoxLayout()
        traits_header.setContentsMargins(0, 0, 0, 0)
        self._traits_title = QLabel(_tr("mutation_planner.selected_traits"))
        self._traits_title.setStyleSheet("color:#8fb8a0; font-size:12px; font-weight:bold;")
        traits_header.addWidget(self._traits_title)
        traits_header.addStretch()
        self._clear_traits_btn = QPushButton(_tr("mutation_planner.clear_all"))
        self._clear_traits_btn.setFixedHeight(22)
        self._clear_traits_btn.setStyleSheet(
            "QPushButton { background:#2a1a1a; color:#c88; border:1px solid #4a2a2a; "
            "border-radius:3px; padding:2px 8px; font-size:10px; }"
            "QPushButton:hover { background:#3a2a2a; }"
        )
        self._clear_traits_btn.clicked.connect(self._on_clear_all_traits)
        traits_header.addWidget(self._clear_traits_btn)
        self._find_pairs_btn = QPushButton(_tr("mutation_planner.find_best_pairs"))
        self._find_pairs_btn.setFixedHeight(22)
        self._find_pairs_btn.setStyleSheet(
            "QPushButton { background:#1f5f4a; color:#f2f7f3; border:1px solid #3f8f72; "
            "border-radius:3px; padding:2px 8px; font-size:10px; font-weight:bold; }"
            "QPushButton:hover { background:#26735a; }"
        )
        self._find_pairs_btn.clicked.connect(self._on_find_best_pairs)
        traits_header.addWidget(self._find_pairs_btn)
        traits_panel_layout.addLayout(traits_header)

        # Scroll area for trait rows
        self._traits_list_widget = QWidget()
        self._traits_list_layout = QVBoxLayout(self._traits_list_widget)
        self._traits_list_layout.setContentsMargins(0, 0, 0, 0)
        self._traits_list_layout.setSpacing(2)
        self._traits_list_layout.addStretch()
        traits_scroll = QScrollArea()
        traits_scroll.setWidgetResizable(True)
        traits_scroll.setFrameShape(QFrame.NoFrame)
        traits_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        traits_scroll.setWidget(self._traits_list_widget)
        traits_panel_layout.addWidget(traits_scroll, 1)
        self._traits_empty_label = QLabel(_tr("mutation_planner.no_traits_selected"))
        self._traits_empty_label.setStyleSheet("color:#555; font-size:10px;")
        self._traits_empty_label.setWordWrap(True)
        traits_panel_layout.addWidget(self._traits_empty_label)
        right_splitter.addWidget(traits_panel)

        # -- Outcome panel --
        self._outcome_scroll = QScrollArea()
        self._outcome_scroll.setWidgetResizable(True)
        self._outcome_scroll.setFrameShape(QFrame.NoFrame)
        self._outcome_scroll.setStyleSheet("QScrollArea { border:none; background:#0a0a18; }")
        self._outcome_widget = QWidget()
        self._outcome_layout = QVBoxLayout(self._outcome_widget)
        self._outcome_layout.setContentsMargins(12, 8, 12, 8)
        self._outcome_layout.setSpacing(6)
        self._outcome_placeholder = QLabel(_tr("mutation_planner.outcome.placeholder_initial"))
        self._outcome_placeholder.setStyleSheet("color:#555; font-size:12px;")
        self._outcome_placeholder.setWordWrap(True)
        self._outcome_layout.addWidget(self._outcome_placeholder)
        self._outcome_layout.addStretch()
        self._outcome_scroll.setWidget(self._outcome_widget)
        right_splitter.addWidget(self._outcome_scroll)

        right_splitter.setSizes([260, 180, 360])
        right_layout.addWidget(right_splitter, 1)
        splitter.addWidget(right)

        splitter.setSizes([500, 500])
        root.addWidget(splitter, 1)
        self.retranslate_ui()

    def retranslate_ui(self):
        self._title.setText(_tr("mutation_planner.title"))
        self._mode_label.setText("Tree:")
        self._show_tree_summary_btn.setText("View Trees")
        self._room_label.setText(_tr("mutation_planner.room"))
        self._stimulation_label.setText(_tr("mutation_planner.stimulation"))
        self._target_trait_label.setText(_tr("mutation_planner.target_trait"))
        self._trait_search.setPlaceholderText(_tr("mutation_planner.search_placeholder"))
        self._deselect_traits_btn.setText(_tr("mutation_planner.deselect_traits", default="Deselect"))
        self._add_trait_btn.setText(_tr("mutation_planner.add_trait", default="Add Desired"))
        self._add_undesired_btn.setText(_tr("mutation_planner.add_undesired", default="Add Undesired"))
        self._remove_trait_btn.setText(_tr("mutation_planner.remove_selected_trait", default="Remove Trait"))
        self._traits_title.setText(_tr("mutation_planner.selected_traits"))
        self._clear_traits_btn.setText(_tr("mutation_planner.clear_all"))
        self._find_pairs_btn.setText(_tr("mutation_planner.find_best_pairs"))
        self._traits_empty_label.setText(_tr("mutation_planner.no_traits_selected"))
        self._refresh_mode_combo_label()
        if self._active_trait_data:
            self._update_trait_detail_panel(self._active_trait_data)
        else:
            self._trait_detail_title.setText(_tr("mutation_planner.target_trait"))
            self._trait_detail_meta.setText(_tr("mutation_planner.no_traits_selected"))
            self._trait_detail_desc.setText(_tr("mutation_planner.no_traits_selected"))
        if len(self._selected_pair) < 2:
            self._pair_label.setText(_tr("mutation_planner.pair_hint"))
            self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        if hasattr(self, "_trait_table"):
            self._trait_table.setHorizontalHeaderLabels([
                "Sel",
                "Trait",
                "Type",
                "Cats",
                "Description",
            ])
        self._cat_table.setHorizontalHeaderLabels([
            _tr("mutation_planner.table.name"),
            _tr("mutation_planner.table.gender"),
            _tr("mutation_planner.table.age"),
            _tr("mutation_planner.table.sum"),
            _tr("mutation_planner.table.mutations"),
            _tr("mutation_planner.table.passives_disorders"),
            _tr("mutation_planner.table.abilities"),
        ])

    def set_cats(self, cats: list[Cat]):
        self._cats = cats
        self._alive_cats = [cat for cat in cats if cat.status != "Gone"]
        self._selected_pair.clear()
        self._populate_room_filter()
        self._populate_trait_combo()
        self._refresh_table()
        self._restore_session_state()
        self._refresh_trait_table_name_styles()

    def set_navigate_to_cat_callback(self, callback):
        self._navigate_to_cat_callback = callback

    def _refresh_mode_combo_label(self):
        if hasattr(self, "_mode_combo"):
            idx = self._mode_combo.findData(self._selected_mode)
            if idx >= 0 and self._mode_combo.currentIndex() != idx:
                self._mode_combo.blockSignals(True)
                self._mode_combo.setCurrentIndex(idx)
                self._mode_combo.blockSignals(False)

    def _on_mode_changed(self, _index: int):
        mode = self._mode_combo.currentData() if hasattr(self, "_mode_combo") else None
        mode = str(mode or "best_pairs").strip().lower()
        if mode not in MUTATION_CLASS_MODES or mode == self._selected_mode:
            return
        self._selected_mode = mode
        self._sync_selected_traits_reference()
        self._rebuild_traits_list()
        self._refresh_trait_table_name_styles()
        self._refresh_table()
        self._clear_outcome_panel()
        self._save_session_state()
        self._notify_traits_changed()

    def _open_tree_summary_dialog(self):
        dialog = _MutationClassSummaryDialog(self.get_mode_profiles(), self)
        dialog.exec()

    def save_session_state(self):
        self._save_session_state()

    def set_save_path(self, save_path: Optional[str], *, refresh_existing: bool = True, notify: bool = True):
        self._save_path = save_path
        if refresh_existing and self._cats:
            self.set_cats(self._cats)
            return
        self._suppress_traits_changed = not notify
        try:
            self._restore_session_state()
            self._refresh_trait_table_name_styles()
        finally:
            self._suppress_traits_changed = False

    def _populate_room_filter(self):
        self._room_combo.blockSignals(True)
        self._room_combo.clear()
        self._room_combo.addItem(_tr("mutation_planner.all_cats"), "")
        rooms: dict[str, str] = {}
        for cat in self._alive_cats:
            if not cat.room or cat.room == "Adventure":
                continue
            if cat.room not in rooms:
                rooms[cat.room] = ROOM_DISPLAY.get(cat.room, cat.room)
        for raw, display in sorted(rooms.items(), key=lambda kv: kv[1]):
            self._room_combo.addItem(display, raw)
        self._room_combo.blockSignals(False)

    def _build_trait_catalog(self):
        """Collect every visible trait across the current cats with counts and details."""
        catalog: dict[tuple[str, str], dict] = {}
        category_order = {
            "mutation": 0,
            "defect": 1,
            "passive": 2,
            "disorder": 3,
            "ability": 4,
        }

        for cat in self._alive_cats:
            def _add_trait(category: str, raw_key: str, display: str, tip: str):
                key = str(raw_key or "").strip().lower()
                if not key:
                    return
                entry = catalog.setdefault((category, key), {
                    "category": category,
                    "key": key,
                    "display": display,
                    "tip": tip,
                    "cats": set(),
                    "order": category_order.get(category, 99),
                })
                if not entry.get("display"):
                    entry["display"] = display
                if tip and not entry.get("tip"):
                    entry["tip"] = tip
                entry["cats"].add(_cat_uid(cat) or str(id(cat)))

            mutation_chip_items = list(getattr(cat, "mutation_chip_items", []) or [])
            for text, tip in mutation_chip_items:
                display = _mutation_display_name(text)
                mid_match = re.search(r'\(ID\s+(-?\d+)\)', tip)
                key = f"{text}|{mid_match.group(1)}" if mid_match else text
                _add_trait("mutation", key, display, tip)
            if not mutation_chip_items:
                for text in (cat.mutations or []):
                    display = _mutation_display_name(text)
                    _add_trait("mutation", text, display, _ability_tip(text))

            defect_chip_items = list(getattr(cat, "defect_chip_items", []) or [])
            for text, tip in defect_chip_items:
                display = _mutation_display_name(text)
                mid_match = re.search(r'\(ID\s+(-?\d+)\)', tip)
                key = f"{text}|{mid_match.group(1)}" if mid_match else text
                _add_trait("defect", key, display, tip)
            if not defect_chip_items:
                for text in (cat.defects or []):
                    display = _mutation_display_name(text)
                    _add_trait("defect", text, display, _ability_tip(text))

            for p in (cat.passive_abilities or []):
                display = _mutation_display_name(p)
                _add_trait("passive", p, display, _ability_tip(p))

            for d in (cat.disorders or []):
                display = _mutation_display_name(d)
                _add_trait("disorder", d, display, _ability_tip(d))

            for a in (cat.abilities or []):
                # Basic attacks come with the class and are never inherited —
                # exclude them from the targetable catalog (Detailed Scoring
                # filters them the same way).
                if is_basic_attack_token(a):
                    continue
                # Collate tiers into one row keyed by the base token (like
                # Detailed Scoring); the family tip shows base + upgraded
                # effects so both forms can be judged from one entry.
                base, _tier = _strip_tier(a)
                display = _mutation_display_name(base)
                _add_trait("ability", base, display, _ability_family_tip(base))

        rows: list[dict] = []
        for entry in catalog.values():
            tip = str(entry.get("tip") or "")
            detail = _trait_visible_detail(tip)
            rows.append({
                "category": entry["category"],
                "key": entry["key"],
                "display": entry["display"],
                "tip": tip,
                "cats": len(entry["cats"]),
                "stats": _trait_selector_summary(tip),
                "desc": detail,
                "kind": _trait_display_kind(entry["category"]),
                "order": entry["order"],
            })

        # Disambiguate mutation/defect variants that share the same display name
        display_counts: Counter = Counter(
            (row["category"], row["display"])
            for row in rows
            if row["category"] in ("mutation", "defect")
        )
        for row in rows:
            if row["category"] in ("mutation", "defect"):
                if display_counts.get((row["category"], row["display"]), 0) > 1 and row["stats"]:
                    row["display"] = f"{row['display']} ({row['stats']})"

        self._trait_catalog = sorted(rows, key=lambda row: (row["order"], row["display"].lower()))

    def _populate_trait_table(self, search: str = "", restore_data=None):
        if not hasattr(self, "_trait_table"):
            return

        needle = search.strip().lower()
        selected_row = -1
        self._trait_table.blockSignals(True)
        self._trait_table.setSortingEnabled(False)
        self._trait_table.setRowCount(0)

        for row_data in self._trait_catalog:
            display_text = _trait_selector_label(row_data["category"], row_data["display"], row_data["tip"])
            if needle:
                hay = " ".join([
                    row_data["display"],
                    row_data["kind"],
                    str(row_data["cats"]),
                    row_data["desc"],
                    row_data["tip"],
                    display_text,
                ]).lower()
                if needle not in hay:
                    continue

            row = self._trait_table.rowCount()
            self._trait_table.insertRow(row)

            weight = _planner_trait_weight(
                self._selected_traits,
                category=row_data["category"],
                key=row_data["key"],
                display=row_data["display"],
            )
            fg, bg = _planner_trait_name_colors(weight)

            sel_item = _SortByUserRoleItem("\u2713" if weight != 0 else "")
            sel_item.setData(Qt.UserRole, abs(weight) if weight != 0 else 0)
            sel_item.setTextAlignment(Qt.AlignCenter)
            if weight != 0:
                sel_item.setForeground(fg)
            self._trait_table.setItem(row, 0, sel_item)

            display_item = QTableWidgetItem(row_data["display"])
            display_item.setData(Qt.UserRole, (row_data["category"], row_data["key"]))
            display_item.setToolTip(row_data["desc"] or row_data["display"])
            display_item.setForeground(fg)
            if bg is not None:
                display_item.setBackground(bg)
                font = display_item.font()
                font.setBold(True)
                display_item.setFont(font)
            self._trait_table.setItem(row, 1, display_item)

            kind_item = _SortByUserRoleItem(row_data["kind"])
            kind_item.setData(Qt.UserRole, row_data["order"])
            kind_item.setTextAlignment(Qt.AlignCenter)
            self._trait_table.setItem(row, 2, kind_item)

            cats_item = _SortByUserRoleItem(str(row_data["cats"]))
            cats_item.setData(Qt.UserRole, row_data["cats"])
            cats_item.setTextAlignment(Qt.AlignCenter)
            self._trait_table.setItem(row, 3, cats_item)

            desc_text = row_data["desc"] or ""
            desc_item = QTableWidgetItem(desc_text)
            if desc_text:
                desc_item.setToolTip(desc_text)
            self._trait_table.setItem(row, 4, desc_item)

            if restore_data is not None and (row_data["category"], row_data["key"]) == restore_data:
                selected_row = row

        self._trait_table.setSortingEnabled(True)
        self._trait_table.blockSignals(False)
        if selected_row >= 0:
            self._trait_table.selectRow(selected_row)

    def _refresh_trait_table_name_styles(self):
        if not hasattr(self, "_trait_table"):
            return
        for row in range(self._trait_table.rowCount()):
            item = self._trait_table.item(row, 1)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            category = key = ""
            if isinstance(data, tuple) and len(data) == 2:
                category, key = data
            weight = _planner_trait_weight(
                self._selected_traits,
                category=category,
                key=key,
                display=item.text(),
            )
            fg, bg = _planner_trait_name_colors(weight)
            item.setForeground(fg)
            if bg is not None:
                item.setBackground(bg)
            else:
                item.setBackground(QColor(0, 0, 0, 0))
            font = item.font()
            font.setBold(weight != 0)
            item.setFont(font)
            sel_item = self._trait_table.item(row, 0)
            if sel_item is not None:
                sel_item.setText("\u2713" if weight != 0 else "")
                sel_item.setData(Qt.UserRole, abs(weight) if weight != 0 else 0)
                if weight != 0:
                    sel_item.setForeground(fg)
                else:
                    sel_item.setForeground(QColor(0, 0, 0, 0))

    def _populate_trait_combo(self):
        prev = self._trait_combo.currentData()
        self._build_trait_catalog()
        self._refresh_selected_traits_metadata()
        self._trait_items_master = [
            (
                _trait_selector_label(row["category"], row["display"], row["tip"]),
                (row["category"], row["key"]),
                row["tip"],
            )
            for row in self._trait_catalog
        ]
        self._apply_trait_filter(self._trait_search.text(), prev)

    def _on_trait_search_changed(self, text: str):
        prev = self._trait_combo.currentData()
        self._apply_trait_filter(text, prev)
        self._save_session_state()

    def _apply_trait_filter(self, search: str, restore_data=None):
        self._trait_combo.blockSignals(True)
        self._trait_combo.clear()
        self._trait_combo.addItem(_tr("mutation_planner.none_trait"), None)

        needle = search.strip().lower()
        last_category = None
        for display_text, user_data, tooltip_text in self._trait_items_master:
            if needle:
                hay = " ".join([display_text, tooltip_text or "", " ".join(map(str, user_data or ())) ]).lower()
                if needle not in hay:
                    continue
            # Insert category separator when category changes
            category = user_data[0] if isinstance(user_data, tuple) else None
            if category != last_category:
                if last_category is not None:
                    self._trait_combo.insertSeparator(self._trait_combo.count())
                last_category = category
            self._trait_combo.addItem(display_text, user_data)
            if tooltip_text:
                tooltip = str(tooltip_text).strip()
                if re.fullmatch(r"[A-Z0-9_]+(?:_DESC)?", tooltip):
                    tooltip = display_text
                if not tooltip:
                    tooltip = display_text
                self._trait_combo.setItemData(self._trait_combo.count() - 1, tooltip, Qt.ToolTipRole)

        # Restore previous selection if still present
        if restore_data is not None:
            for i in range(self._trait_combo.count()):
                if self._trait_combo.itemData(i) == restore_data:
                    self._trait_combo.setCurrentIndex(i)
                    break
        self._trait_combo.blockSignals(False)

        if hasattr(self, "_trait_table"):
            self._populate_trait_table(search, restore_data)

    def _activate_trait_filter(self, trait_data: tuple[str, str] | None, *, source: str = "combo"):
        if self._restoring_session_state:
            return
        self._active_trait_data = trait_data if isinstance(trait_data, tuple) else None
        self._browse_trait_datas = [self._active_trait_data] if self._active_trait_data is not None else []

        # Keep the combo, trait table, and cat list aligned without recursive signal churn.
        if source != "combo":
            self._trait_combo.blockSignals(True)
            if self._active_trait_data is None:
                self._trait_combo.setCurrentIndex(0)
            else:
                for i in range(self._trait_combo.count()):
                    if self._trait_combo.itemData(i) == self._active_trait_data:
                        self._trait_combo.setCurrentIndex(i)
                        break
            self._trait_combo.blockSignals(False)

        if source != "trait_table" and hasattr(self, "_trait_table"):
            self._trait_table.blockSignals(True)
            if self._active_trait_data is None:
                self._trait_table.clearSelection()
            else:
                for row in range(self._trait_table.rowCount()):
                    item = self._trait_table.item(row, 1)
                    if item is not None and item.data(Qt.UserRole) == self._active_trait_data:
                        self._trait_table.selectRow(row)
                        break
            self._trait_table.blockSignals(False)

        self._cat_table.blockSignals(True)
        self._cat_table.clearSelection()
        self._cat_table.blockSignals(False)
        self._selected_pair.clear()
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._update_trait_detail_panel(self._active_trait_data)
        self._clear_outcome_panel()
        self._refresh_table()

    def _update_trait_detail_panel(self, trait_data: tuple[str, str] | None):
        if not hasattr(self, "_trait_detail_meta"):
            return
        if trait_data is None:
            self._trait_detail_title.setText(_tr("mutation_planner.target_trait"))
            self._trait_detail_meta.setText(_tr("mutation_planner.no_traits_selected"))
            self._trait_detail_desc.setText(_tr("mutation_planner.no_traits_selected"))
            self._trait_info_label.setText("")
            self._trait_info_label.setStyleSheet("color:#666; font-size:11px;")
            return

        category, key = trait_data
        row_data = next((row for row in self._trait_catalog if row["category"] == category and row["key"] == key), None)
        if row_data is None:
            self._trait_detail_title.setText(_tr("mutation_planner.target_trait"))
            self._trait_detail_meta.setText("")
            self._trait_detail_desc.setText("")
            self._trait_info_label.setText("")
            return

        title = _trait_selector_label(row_data["category"], row_data["display"], row_data["tip"])
        self._trait_detail_title.setText(title)
        meta_bits = [row_data["kind"], _tr("mutation_planner.trait_info.carriers_found", count=row_data["cats"])]
        if row_data["stats"]:
            meta_bits.append(row_data["stats"])
        self._trait_detail_meta.setText("  ".join(meta_bits))
        desc = row_data["desc"] or _tr("mutation_planner.no_description", default="No description available")
        self._trait_detail_desc.setText(desc)
        self._trait_info_label.setText(_tr("mutation_planner.trait_info.carriers_found", count=row_data["cats"]))
        self._trait_info_label.setStyleSheet("color:#8fb8a0; font-size:11px;")

    def _on_target_trait_changed(self):
        data = self._trait_combo.currentData()
        if data is None:
            self._activate_trait_filter(None, source="combo")
            if len(self._selected_pair) == 2:
                self._update_outcome_panel(self._selected_pair[0], self._selected_pair[1])
            else:
                self._clear_outcome_panel()
            self._save_session_state()
            return
        self._cat_table.clearSelection()
        self._activate_trait_filter(data, source="combo")
        self._save_session_state()

    def _on_trait_table_selection_changed(self):
        if self._restoring_session_state or self._syncing_trait_selection or not hasattr(self, "_trait_table"):
            return
        trait_datas = self._selected_trait_datas_from_table()
        self._browse_trait_datas = list(trait_datas)
        self._active_trait_data = trait_datas[-1] if trait_datas else None
        self._update_trait_detail_panel(self._active_trait_data)
        self._selected_pair.clear()
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._clear_outcome_panel()
        self._refresh_table()
        self._save_session_state()

    # ── Multi-select trait management ──

    def _selected_trait_datas_from_table(self) -> list[tuple[str, str]]:
        if not hasattr(self, "_trait_table"):
            return []
        datas: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        rows = sorted(set(idx.row() for idx in self._trait_table.selectionModel().selectedRows()))
        for row in rows:
            item = self._trait_table.item(row, 1)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            if isinstance(data, tuple) and len(data) == 2 and data not in seen:
                seen.add(data)
                datas.append((str(data[0]), str(data[1])))
        return datas

    def _sync_trait_table_selection(self, trait_datas: list[tuple[str, str]]):
        if not hasattr(self, "_trait_table"):
            return
        table = self._trait_table
        sel_model = table.selectionModel()
        if sel_model is None:
            return
        wanted = {tuple(d) for d in trait_datas}
        table.blockSignals(True)
        sel_model.blockSignals(True)
        try:
            table.clearSelection()
            if not wanted:
                return
            for row in range(table.rowCount()):
                item = table.item(row, 1)
                if item is None:
                    continue
                data = item.data(Qt.UserRole)
                if isinstance(data, tuple) and tuple(data) in wanted:
                    table.selectRow(row)
        finally:
            sel_model.blockSignals(False)
            table.blockSignals(False)

    def _set_selected_traits_from_datas(
        self,
        trait_datas: list[tuple[str, str]],
        *,
        sync_table: bool,
        clear_combo: bool,
    ):
        trait_lookup = {(row["category"], row["key"]): row for row in self._trait_catalog}
        existing_weights = {
            (trait["category"], trait["key"]): int(trait.get("weight", 5))
            for trait in self._selected_traits
        }
        new_traits: list[dict] = []
        for category, key in trait_datas:
            row_data = trait_lookup.get((category, key))
            if row_data is None:
                continue
            new_traits.append({
                "category": category,
                "key": key,
                "display": row_data["display"],
                "weight": existing_weights.get((category, key), 5),
            })

        self._set_active_mode_traits(new_traits)
        self._selected_pair.clear()
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._active_trait_data = trait_datas[-1] if trait_datas else None
        self._cat_table.blockSignals(True)
        self._cat_table.clearSelection()
        self._cat_table.blockSignals(False)

        if clear_combo and hasattr(self, "_trait_combo"):
            self._trait_combo.blockSignals(True)
            self._trait_combo.setCurrentIndex(0)
            self._trait_combo.blockSignals(False)

        self._rebuild_traits_list()
        self._refresh_trait_table_name_styles()
        self._clear_outcome_panel()
        self._refresh_table()
        self._save_session_state()
        self._notify_traits_changed()

    def _on_add_trait(self):
        """Add the currently selected left-table traits with weight 5, overriding if already present."""
        self._add_traits_with_weight(5)

    def _on_add_undesired_trait(self):
        """Add the currently selected left-table traits with weight -5, overriding if already present."""
        self._add_traits_with_weight(-5)

    def _add_traits_with_weight(self, weight: int):
        trait_datas = self._selected_trait_datas_from_table()
        if not trait_datas:
            return
        incoming = set(trait_datas)
        trait_lookup = {(row["category"], row["key"]): row for row in self._trait_catalog}
        # Override weight for existing traits
        for trait in self._selected_traits:
            if (trait["category"], trait["key"]) in incoming:
                trait["weight"] = weight
                incoming.discard((trait["category"], trait["key"]))
        # Add new traits
        for category, key in incoming:
            row_data = trait_lookup.get((category, key))
            if row_data is None:
                continue
            self._selected_traits.append({
                "category": category,
                "key": key,
                "display": row_data["display"],
                "weight": weight,
            })
        self._set_active_mode_traits(list(self._selected_traits))
        self._rebuild_traits_list()
        self._refresh_trait_table_name_styles()
        self._refresh_table()
        self._save_session_state()
        self._notify_traits_changed()

    def _on_clear_all_traits(self):
        self._selected_traits.clear()
        self._browse_trait_datas = []
        if hasattr(self, "_trait_table"):
            self._trait_table.blockSignals(True)
            self._trait_table.clearSelection()
            self._trait_table.blockSignals(False)
        self._cat_table.blockSignals(True)
        self._cat_table.clearSelection()
        self._cat_table.blockSignals(False)
        if hasattr(self, "_trait_combo"):
            self._trait_combo.blockSignals(True)
            self._trait_combo.setCurrentIndex(0)
            self._trait_combo.blockSignals(False)
        self._active_trait_data = None
        self._selected_pair.clear()
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._rebuild_traits_list()
        self._refresh_trait_table_name_styles()
        self._clear_outcome_panel()
        self._refresh_table()
        self._save_session_state()
        self._notify_traits_changed()

    def _on_deselect_traits(self):
        if hasattr(self, "_trait_table"):
            self._trait_table.blockSignals(True)
            self._trait_table.clearSelection()
            self._trait_table.blockSignals(False)
        if hasattr(self, "_trait_combo"):
            self._trait_combo.blockSignals(True)
            self._trait_combo.setCurrentIndex(0)
            self._trait_combo.blockSignals(False)
        self._browse_trait_datas = []
        self._active_trait_data = None
        self._selected_pair.clear()
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._update_trait_detail_panel(None)
        self._clear_outcome_panel()
        self._refresh_trait_table_name_styles()
        self._refresh_table()
        self._save_session_state()

    def _on_remove_selected_trait(self):
        """Remove traits currently highlighted in the left trait table from the selected list."""
        trait_datas = self._selected_trait_datas_from_table()
        if not trait_datas:
            return
        remove_set = set(trait_datas)
        remaining = [
            (t["category"], t["key"])
            for t in self._selected_traits
            if (t["category"], t["key"]) not in remove_set
        ]
        self._selected_traits.clear()
        if remaining:
            self._set_selected_traits_from_datas(remaining, sync_table=False, clear_combo=True)
        else:
            self._set_active_mode_traits([])
            self._rebuild_traits_list()
            self._refresh_trait_table_name_styles()
            self._refresh_table()
            self._save_session_state()
            self._notify_traits_changed()
            self._notify_traits_changed()

    def _on_remove_trait(self, index: int):
        if 0 <= index < len(self._selected_traits):
            self._selected_traits.pop(index)
            self._set_selected_traits_from_datas(
                [(trait["category"], trait["key"]) for trait in self._selected_traits],
                sync_table=False,
                clear_combo=True,
            )

    def _on_trait_weight_changed(self, index: int, value: int):
        if 0 <= index < len(self._selected_traits):
            self._selected_traits[index]["weight"] = value
            self._rebuild_traits_list()
            self._refresh_trait_table_name_styles()
            self._save_session_state()
            self._notify_traits_changed()

    def _rebuild_traits_list(self):
        """Rebuild the selected traits list UI."""
        layout = self._traits_list_layout
        # Clear all widgets except the stretch at the end
        while layout.count() > 1:
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self._traits_empty_label.setVisible(len(self._selected_traits) == 0)

        for i, trait in enumerate(self._selected_traits):
            row = QWidget()
            row.setStyleSheet("QWidget { background:#151530; border-radius:3px; }")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(6, 4, 4, 4)
            row_layout.setSpacing(3)

            top = QWidget()
            top.setStyleSheet("background:transparent;")
            top_layout = QHBoxLayout(top)
            top_layout.setContentsMargins(0, 0, 0, 0)
            top_layout.setSpacing(6)

            lbl = QToolButton()
            lbl.setText(str(trait.get("display") or trait.get("key") or "?"))
            lbl.setToolButtonStyle(Qt.ToolButtonTextOnly)
            lbl.setAutoRaise(True)
            lbl.setCursor(Qt.PointingHandCursor)
            fg_hex, bg_hex, border_hex = _planner_trait_name_palette(trait.get("weight", 0))
            if bg_hex:
                lbl.setStyleSheet(
                    "QToolButton {"
                    f" color:{fg_hex}; background:{bg_hex}; border:1px solid {border_hex};"
                    " border-radius:3px; padding:2px 4px; font-size:10px; text-align:left; }"
                )
            else:
                lbl.setStyleSheet("QToolButton { color:#ccc; font-size:10px; border:none; background:transparent; text-align:left; }")
            lbl.clicked.connect(lambda _checked=False, t=trait: self._activate_trait_filter((t["category"], t["key"]), source="selected_trait"))
            top_layout.addWidget(lbl, 1)

            wt_label = QLabel(_tr("mutation_planner.weight_short"))
            wt_label.setStyleSheet("color:#888; font-size:10px;")
            top_layout.addWidget(wt_label)

            spin = QSpinBox()
            spin.setRange(-10, 10)
            spin.setValue(trait["weight"])
            spin.setFixedWidth(45)

            def _spin_style(v):
                if v < 0:
                    return ("QSpinBox { background:#0d0d1c; color:#c86060; border:1px solid #2a2a4a;"
                            " border-radius:3px; padding:1px; font-size:10px; }")
                return ("QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
                        " border-radius:3px; padding:1px; font-size:10px; }")

            spin.setStyleSheet(_spin_style(trait["weight"]))
            idx = i  # capture for lambda
            spin.valueChanged.connect(lambda v, ii=idx, s=spin: (
                self._on_trait_weight_changed(ii, v),
                s.setStyleSheet(
                    "QSpinBox { background:#0d0d1c; color:#c86060; border:1px solid #2a2a4a;"
                    " border-radius:3px; padding:1px; font-size:10px; }" if v < 0
                    else "QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
                    " border-radius:3px; padding:1px; font-size:10px; }"
                )
            ))
            top_layout.addWidget(spin)

            remove_btn = QPushButton(_tr("mutation_planner.remove_trait"))
            remove_btn.setFixedSize(20, 20)
            remove_btn.setStyleSheet(
                "QPushButton { background:#2a1a1a; color:#c88; border:none; "
                "border-radius:3px; font-size:10px; font-weight:bold; }"
                "QPushButton:hover { background:#3a2a2a; }"
            )
            remove_btn.clicked.connect(lambda _, ii=idx: self._on_remove_trait(ii))
            top_layout.addWidget(remove_btn)
            row_layout.addWidget(top)

            meta_parts: list[str] = []
            kind = str(trait.get("kind") or "").strip()
            if kind:
                meta_parts.append(kind)
            carriers = int(trait.get("cats", 0) or 0)
            if carriers > 0:
                meta_parts.append(f"{carriers} carriers")
            stats = str(trait.get("stats") or "").strip()
            if stats:
                meta_parts.append(stats)
            if meta_parts:
                meta_label = QLabel("  |  ".join(meta_parts))
                meta_label.setWordWrap(True)
                meta_label.setStyleSheet("color:#8d8da8; font-size:10px;")
                row_layout.addWidget(meta_label)

            desc = str(trait.get("desc") or "").strip()
            if desc:
                desc_label = QLabel(desc)
                desc_label.setWordWrap(True)
                desc_label.setStyleSheet("color:#9ea8c6; font-size:10px;")
                row_layout.addWidget(desc_label)

            layout.insertWidget(layout.count() - 1, row)  # insert before stretch

    def _on_find_best_pairs(self):
        """Find the best breeding pairs to cover all selected traits."""
        if not self._selected_traits:
            return
        self._cat_table.clearSelection()
        self._selected_pair.clear()
        self._active_trait_data = None
        self._pair_label.setText(_tr("mutation_planner.pair_hint"))
        self._pair_label.setStyleSheet("color:#666; font-size:11px;")
        self._trait_combo.blockSignals(True)
        self._trait_combo.setCurrentIndex(0)
        self._trait_combo.blockSignals(False)
        if hasattr(self, "_trait_table"):
            self._trait_table.clearSelection()
        self._update_trait_detail_panel(None)
        self._trait_info_label.setText("")
        self._refresh_table()
        self._update_multi_trait_plan()
        self._session_state["has_multi_trait_results"] = bool(self._selected_traits)
        self._save_session_state()

    def _update_multi_trait_plan(self):
        """Show breeding plan for multiple selected traits with weights."""
        stim = self._stim_spin.value()
        traits = self._selected_traits

        # Get all alive cats, excluding blacklisted
        alive = [c for c in self._alive_cats if not c.is_blacklisted]

        # Score each cat: how many of the selected traits does it carry?
        def _cat_score(cat):
            return sum(t["weight"] for t in traits if _cat_has_trait(cat, t["category"], t["key"]))

        # Generate all candidate pairs via can_breed (respects sexuality overrides)
        candidate_pairs = []
        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                ok, _ = can_breed(a, b)
                if ok:
                    candidate_pairs.append((a, b))

        max_possible = sum(t["weight"] for t in traits if t["weight"] > 0)
        # With both-parents bonus: max is weight * 1.5 per positive trait
        max_score_with_bonus = max_possible * 1.5

        scored_pairs: list[tuple] = []
        for a, b in candidate_pairs:
            score = 0.0
            covered = []      # positive-weight traits covered by at least one parent
            uncovered = []    # positive-weight traits not covered
            penalized = []    # negative-weight traits carried by at least one parent
            for t in traits:
                a_has = _cat_has_trait(a, t["category"], t["key"])
                b_has = _cat_has_trait(b, t["category"], t["key"])
                w = t["weight"]
                if w < 0:
                    if a_has or b_has:
                        score += w  # penalty
                        if a_has and b_has:
                            score += w * 0.5  # extra penalty if both carry it
                        penalized.append(t)
                else:
                    if a_has or b_has:
                        score += w
                        if a_has and b_has:
                            score += w * 0.5  # bonus for both carriers
                        covered.append(t)
                    else:
                        uncovered.append(t)
            if covered:  # only show pairs that cover at least one positive trait
                pair_risk = risk_percent(a, b)
                scored_pairs.append((score, a, b, covered, uncovered, penalized, pair_risk))

        scored_pairs.sort(key=lambda x: (-x[0], x[6]))  # best score, lowest birth-defect risk

        # Build outcome panel
        layout = self._outcome_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        layout.addWidget(self._sec_label(
            _tr("mutation_planner.multi_trait.title", count=len(traits), max=max_possible)
        ))

        if not scored_pairs:
            layout.addWidget(self._info_label(_tr("mutation_planner.multi_trait.no_pairs")))
            layout.addStretch()
            return

        # Check if any pair covers all positive traits
        pos_traits = [t for t in traits if t["weight"] > 0]
        best_score = scored_pairs[0][0]
        full_coverage = [p for p in scored_pairs if not p[4]]  # no uncovered positive traits

        if full_coverage:
            layout.addWidget(self._info_label(
                f"{len(full_coverage)} pair(s) can cover ALL positive traits."
            ))
        else:
            best_covered = len(scored_pairs[0][3])
            layout.addWidget(
                self._info_label(
                    _tr("mutation_planner.multi_trait.best_coverage", total=len(pos_traits), covered=best_covered)
                )
            )

        # Show top pairs (limit to 20)
        layout.addWidget(self._sec_label(_tr("mutation_planner.multi_trait.best_pairs")))
        show_pairs = scored_pairs[:20]

        pair_table = QTableWidget(len(show_pairs), 6)
        pair_table.setHorizontalHeaderLabels([
            _tr("mutation_planner.multi_trait.table.parent_a"),
            _tr("mutation_planner.multi_trait.table.parent_b"),
            _tr("mutation_planner.multi_trait.table.score"),
            _tr("mutation_planner.multi_trait.table.coverage"),
            _tr("mutation_planner.multi_trait.table.uncovered"),
            _tr("mutation_planner.multi_trait.table.inbreeding"),
        ])
        pair_table.verticalHeader().setVisible(False)
        pair_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        pair_table.setSelectionMode(QAbstractItemView.SingleSelection)
        pair_table.setMaximumHeight(min(30 + len(show_pairs) * 26, 500))
        pair_table.setStyleSheet(
            "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; font-size:11px; }"
        )
        phh = pair_table.horizontalHeader()
        phh.setSectionResizeMode(0, QHeaderView.Stretch)
        phh.setSectionResizeMode(1, QHeaderView.Stretch)
        phh.setSectionResizeMode(2, QHeaderView.Interactive)
        phh.setSectionResizeMode(3, QHeaderView.Stretch)
        phh.setSectionResizeMode(4, QHeaderView.Stretch)
        phh.setSectionResizeMode(5, QHeaderView.Interactive)
        pair_table.setColumnWidth(2, 55)
        pair_table.setColumnWidth(5, 70)
        pair_table.cellClicked.connect(self._on_pair_table_clicked)
        pair_table.setMouseTracking(True)
        pair_table.cellEntered.connect(lambda r, c: pair_table.setCursor(
            Qt.PointingHandCursor if c in (0, 1) else Qt.ArrowCursor
        ))

        for row, (score, a, b, covered, uncovered, penalized, pair_risk) in enumerate(show_pairs):
            a_item = QTableWidgetItem(f"{a.name} ({a.gender_display})")
            a_item.setData(Qt.UserRole, a.db_key)
            a_icon = _make_tag_icon(_cat_tags(a), dot_size=14, spacing=4)
            if not a_icon.isNull():
                a_item.setIcon(a_icon)
            a_item.setForeground(QColor("#5b9bd5"))
            a_item.setToolTip(_tr("mutation_planner.tooltip.jump_to_cat"))
            pair_table.setItem(row, 0, a_item)

            b_item = QTableWidgetItem(f"{b.name} ({b.gender_display})")
            b_item.setData(Qt.UserRole, b.db_key)
            b_icon = _make_tag_icon(_cat_tags(b), dot_size=14, spacing=4)
            if not b_icon.isNull():
                b_item.setIcon(b_icon)
            b_item.setForeground(QColor("#5b9bd5"))
            b_item.setToolTip(_tr("mutation_planner.tooltip.jump_to_cat"))
            pair_table.setItem(row, 1, b_item)

            score_item = QTableWidgetItem(f"{score:.0f}/{max_possible}")
            score_item.setTextAlignment(Qt.AlignCenter)
            if score >= max_possible:
                score_item.setForeground(QColor("#8fb8a0"))
            elif score < 0:
                score_item.setForeground(QColor("#cc6666"))
            pair_table.setItem(row, 2, score_item)

            cov_html = ", ".join(
                _planner_trait_name_html(t["display"].split("] ")[-1], t.get("weight", 0))
                for t in covered
            )
            cov_label = QLabel(cov_html or "—")
            cov_label.setTextFormat(Qt.RichText)
            cov_label.setWordWrap(True)
            cov_label.setStyleSheet("background:transparent; color:#ddd; padding:2px 4px;")
            pair_table.setCellWidget(row, 3, cov_label)

            # Build uncovered + penalized cell
            parts = []
            if uncovered:
                parts.append(", ".join(
                    _planner_trait_name_html(t["display"].split("] ")[-1], t.get("weight", 0))
                    for t in uncovered
                ))
            if penalized:
                parts.append(
                    "\u26a0 "
                    + ", ".join(
                        _planner_trait_name_html(t["display"].split("] ")[-1], t.get("weight", 0))
                        for t in penalized
                    )
                )
            if parts:
                unc_label = QLabel(" | ".join(parts))
                unc_label.setTextFormat(Qt.RichText)
                unc_label.setWordWrap(True)
                unc_label.setStyleSheet(
                    "background:transparent;"
                    + (" color:#cc8833;" if penalized else " color:#cc6666;")
                    + " padding:2px 4px;"
                )
                pair_table.setCellWidget(row, 4, unc_label)
            else:
                full_item = QTableWidgetItem(_tr("mutation_planner.multi_trait.all_covered"))
                full_item.setForeground(QColor("#8fb8a0"))
                pair_table.setItem(row, 4, full_item)

            risk_pct = int(round(pair_risk))
            inbred_item = QTableWidgetItem(f"{risk_pct}%")
            inbred_item.setTextAlignment(Qt.AlignCenter)
            if risk_pct >= 100:
                inbred_item.setForeground(QColor("#d97777"))
            elif risk_pct >= 50:
                inbred_item.setForeground(QColor("#d8b56a"))
            elif risk_pct >= 20:
                inbred_item.setForeground(QColor("#8fc9e6"))
            pair_table.setItem(row, 5, inbred_item)

        layout.addWidget(pair_table)

        # Per-trait carrier summary
        layout.addWidget(self._sec_label(_tr("mutation_planner.multi_trait.carrier_summary")))
        for t in traits:
            carriers = [c for c in alive if _cat_has_trait(c, t["category"], t["key"])]
            trait_short = t["display"].split("] ")[-1]
            w = t["weight"]
            if w < 0:
                prefix = "\u26a0 "
                color = "#cc8833" if carriers else "#888"
            else:
                prefix = ""
                color = "#8fb8a0" if carriers else "#cc6666"
            lbl = self._info_label(
                f"  {prefix}{trait_short} (wt {w}): {len(carriers)} carrier(s)"
                + (f" -- {', '.join(c.name for c in carriers[:8])}" if carriers else " -- NONE")
            )
            lbl.setStyleSheet(f"color:{color}; font-size:11px;")
            layout.addWidget(lbl)

        layout.addStretch()

    def _on_pair_table_clicked(self, row: int, col: int):
        """Navigate to a cat in the Alive Cats view when its name is clicked."""
        if col not in (0, 1):
            return
        table = self.sender()
        item = table.item(row, col)
        if item is None:
            return
        db_key = item.data(Qt.UserRole)
        if db_key is not None and self._navigate_to_cat_callback is not None:
            self._navigate_to_cat_callback(db_key)

    def get_selected_traits(self) -> list[dict]:
        """Return current selected traits with weights (for export to room optimizer)."""
        source = self.get_traits_for_mode(self._selected_mode)
        if source:
            return source
        state = self._session_state if isinstance(self._session_state, dict) else {}
        selected_mode = str(state.get("selected_mode", self._selected_mode) or self._selected_mode).strip().lower()
        mode_profiles = _normalize_mutation_mode_profiles(
            state.get("mode_profiles", {}),
            legacy_traits=state.get("selected_traits", []),
        )
        return [dict(t) for t in mode_profiles.get(selected_mode, {}).get("traits", [])]

    def _session_state_payload(self) -> dict:
        state = dict(self._session_state) if isinstance(self._session_state, dict) else {}
        selected_pair_uids = [_cat_uid(cat) for cat in self._selected_pair if _cat_uid(cat)]
        current_trait = self._trait_combo.currentData()
        mode_profiles = self.get_mode_profiles()
        state.update({
            "room": self._room_combo.currentData() or "",
            "stim": int(self._stim_spin.value()),
            "search": self._trait_search.text(),
            "trait_data": list(current_trait) if isinstance(current_trait, tuple) else None,
            "selected_mode": self._selected_mode,
            "mode_profiles": mode_profiles,
            "selected_traits": [dict(t) for t in mode_profiles.get(self._selected_mode, {}).get("traits", [])],
            "selected_pair_uids": selected_pair_uids if len(selected_pair_uids) == 2 else [],
            "last_mode": state.get("last_mode", "none"),
        })
        if state["selected_traits"]:
            state["last_mode"] = "multi"
        elif state["selected_pair_uids"]:
            state["last_mode"] = "pair"
        elif state["trait_data"] is not None:
            state["last_mode"] = "single"
        return state

    def _save_session_state(self):
        if getattr(self, "_restoring_session_state", False):
            return
        self._session_state = self._session_state_payload()
        _save_planner_state_value("mutation_planner_state", self._session_state, self._save_path)

    def _restore_session_state(self):
        state = _load_planner_state_value("mutation_planner_state", {}, self._save_path)
        if not isinstance(state, dict):
            state = {}
        self._session_state = state
        self._restoring_session_state = True
        try:
            room_value = str(state.get("room", "") or "")
            idx = self._room_combo.findData(room_value)
            self._room_combo.setCurrentIndex(idx if idx >= 0 else 0)

            self._stim_spin.setValue(int(state.get("stim", 10) or 10))

            selected_mode = str(state.get("selected_mode", "best_pairs") or "best_pairs").strip().lower()
            if selected_mode not in MUTATION_CLASS_MODES:
                selected_mode = "best_pairs"
            self._selected_mode = selected_mode
            self._mode_profiles = _normalize_mutation_mode_profiles(
                state.get("mode_profiles", {}),
                legacy_traits=state.get("selected_traits", []),
            )
            self._sync_selected_traits_reference()
            self._refresh_selected_traits_metadata()
            self._refresh_mode_combo_label()
            self._rebuild_traits_list()

            trait_data = state.get("trait_data")
            if isinstance(trait_data, (list, tuple)) and len(trait_data) == 2:
                restored_trait = (str(trait_data[0]), str(trait_data[1]).strip().lower())
                for i in range(self._trait_combo.count()):
                    if self._trait_combo.itemData(i) == restored_trait:
                        self._trait_combo.setCurrentIndex(i)
                        break

            pair_uids = state.get("selected_pair_uids", [])
            if isinstance(pair_uids, list) and len(pair_uids) == 2:
                uid_map = {_cat_uid(cat): cat for cat in self._cats}
                pair_cats = [uid_map.get(str(uid).strip().lower()) for uid in pair_uids]
                if all(pair_cats):
                    self._selected_pair = [pair_cats[0], pair_cats[1]]
        finally:
            self._restoring_session_state = False

        current_trait = self._trait_combo.currentData()
        if state.get("has_multi_trait_results") and self._selected_traits and self._alive_cats:
            self._on_find_best_pairs()
        elif isinstance(current_trait, tuple):
            self._activate_trait_filter(current_trait, source="combo")
        else:
            self._clear_outcome_panel()
        self._notify_traits_changed()

    def reset_to_defaults(self):
        """Restore the mutation planner to its default room, search, and layout state.

        Preserves selected traits and mode profiles so the user does not lose
        their trait selections.
        """
        self._session_state = {}
        self._restoring_session_state = True
        try:
            self._refresh_mode_combo_label()
            if self._room_combo.count():
                self._room_combo.setCurrentIndex(0)
            self._stim_spin.setValue(10)
            self._trait_search.setText("")
            self._selected_pair.clear()
            self._active_trait_data = None
            self._browse_trait_datas = []
            self._pair_label.setText(_tr("mutation_planner.pair_hint"))
            self._pair_label.setStyleSheet("color:#666; font-size:11px;")
            if self._trait_combo.count():
                self._trait_combo.setCurrentIndex(0)
            self._cat_table.clearSelection()
            if hasattr(self, "_trait_table"):
                self._trait_table.clearSelection()
            self._update_trait_detail_panel(None)
            self._clear_outcome_panel()
            self._rebuild_traits_list()
            if hasattr(self, "_splitter"):
                self._splitter.setSizes([500, 500])
            if hasattr(self, "_right_splitter"):
                self._right_splitter.setSizes([260, 180, 360])
        finally:
            self._restoring_session_state = False
        self.retranslate_ui()
        self._refresh_table()
        self._notify_traits_changed()
        self._save_session_state()

    def _update_trait_plan(self, trait_data: tuple):
        """Show breeding plan for the selected target trait (single-trait mode)."""
        category, trait_key = trait_data
        stim = self._stim_spin.value()

        # Find all alive cats that have this trait, excluding blacklisted
        carriers: list[Cat] = []
        for cat in self._cats:
            if cat.status == "Gone" or cat.is_blacklisted:
                continue
            if _cat_has_trait(cat, category, trait_key):
                carriers.append(cat)

        # Display name for the trait
        trait_display = self._trait_combo.currentText()
        self._trait_info_label.setText(_tr("mutation_planner.trait_info.carriers_found", count=len(carriers)))
        self._trait_info_label.setStyleSheet(
            f"color:{'#8fb8a0' if carriers else '#cc6666'}; font-size:11px;"
        )

        # Clear and rebuild outcome panel
        layout = self._outcome_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not carriers:
            layout.addWidget(self._info_label(_tr("mutation_planner.single_trait.no_carriers")))
            layout.addStretch()
            return

        carrier_table = QTableWidget(len(carriers), 4)
        carrier_table.setHorizontalHeaderLabels([
            _tr("mutation_planner.table.name"),
            _tr("mutation_planner.table.gender"),
            _tr("mutation_planner.table.age"),
            _tr("mutation_planner.table.room"),
        ])
        carrier_table.verticalHeader().setVisible(False)
        carrier_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        carrier_table.setSelectionMode(QAbstractItemView.NoSelection)
        carrier_table.setMaximumHeight(min(30 + len(carriers) * 26, 250))
        carrier_table.setStyleSheet(
            "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; font-size:11px; }"
        )
        chh = carrier_table.horizontalHeader()
        chh.setSectionResizeMode(0, QHeaderView.Stretch)
        chh.setSectionResizeMode(1, QHeaderView.Interactive)
        chh.setSectionResizeMode(2, QHeaderView.Interactive)
        chh.setSectionResizeMode(3, QHeaderView.Stretch)
        carrier_table.setColumnWidth(1, 50)
        carrier_table.setColumnWidth(2, 40)
        for row, cat in enumerate(carriers):
            carrier_table.setItem(row, 0, QTableWidgetItem(cat.name))
            g_item = QTableWidgetItem(cat.gender_display if hasattr(cat, 'gender_display') else cat.gender)
            g_item.setTextAlignment(Qt.AlignCenter)
            carrier_table.setItem(row, 1, g_item)
            a_item = QTableWidgetItem(str(cat.age) if cat.age is not None else "-")
            a_item.setTextAlignment(Qt.AlignCenter)
            carrier_table.setItem(row, 2, a_item)
            room_name = ROOM_DISPLAY.get(cat.room, cat.room) if cat.room else "-"
            carrier_table.setItem(row, 3, QTableWidgetItem(room_name))
        layout.addWidget(carrier_table)

        # ── Inheritance mechanics ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.single_trait.inheritance")))
        if category == "mutation":
            favor_weight = _stimulation_inheritance_weight(stim)
            layout.addWidget(self._info_label(
                _tr("mutation_planner.single_trait.mutation_help", favor=f"{favor_weight*100:.1f}", stim=stim)
            ))
        elif category == "defect":
            favor_weight = _stimulation_inheritance_weight(stim)
            layout.addWidget(self._info_label(
                _tr(
                    "mutation_planner.single_trait.defect_help",
                    default=("Birth defects inherit like visual mutations ({favor}% from the defective "
                             "parent at {stim} stimulation), but since game 1.1 the roll uses "
                             "effective stimulation = stim − 2 × the kitten's inbreeding %. "
                             "Inbred pairs pass defects on much more often."),
                    favor=f"{favor_weight*100:.1f}",
                    stim=stim,
                )
            ))
        elif category == "passive":
            passive_chance = 0.05 + 0.01 * stim
            layout.addWidget(self._info_label(
                _tr("mutation_planner.single_trait.passive_help", chance=f"{min(passive_chance, 1.0)*100:.1f}", stim=stim)
            ))
        elif category == "ability":
            spell_chance = 0.2 + 0.025 * stim
            layout.addWidget(self._info_label(
                _tr("mutation_planner.single_trait.ability_help", chance=f"{min(spell_chance, 1.0)*100:.1f}", stim=stim)
            ))

        # ── Recommended pairs ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.single_trait.recommended_pairs")))

        males = [c for c in carriers if c.gender and c.gender.upper() in ("M", "MALE")]
        females = [c for c in carriers if c.gender and c.gender.upper() in ("F", "FEMALE")]
        non_carriers = [c for c in self._cats if c.status != "Gone" and not c.is_blacklisted and c not in carriers]
        nc_males = [c for c in non_carriers if c.gender and c.gender.upper() in ("M", "MALE")]
        nc_females = [c for c in non_carriers if c.gender and c.gender.upper() in ("F", "FEMALE")]

        pairs: list[tuple[Cat, Cat, str]] = []  # (cat_a, cat_b, note)

        # Best: carrier x carrier (opposite gender)
        for m in males:
            for f in females:
                if m is f:
                    continue
                pair_risk = risk_percent(m, f)
                note = _tr("mutation_planner.single_trait.note.both_carriers")
                if pair_risk >= 20:
                    note += f" (birth defect risk {int(round(pair_risk))}%)"
                pairs.append((m, f, note))

        # Good: carrier x non-carrier (opposite gender)
        if len(pairs) < 10:
            for carrier in carriers:
                pool = nc_females if carrier.gender and carrier.gender.upper() in ("M", "MALE") else nc_males
                for partner in pool[:5]:  # limit to avoid huge lists
                    pairs.append((carrier, partner, _tr("mutation_planner.single_trait.note.one_carrier")))
                    if len(pairs) >= 15:
                        break
                if len(pairs) >= 15:
                    break

        if not pairs:
            if len(carriers) == 1:
                layout.addWidget(self._info_label(_tr("mutation_planner.single_trait.only_one_carrier", name=carriers[0].name)))
            else:
                layout.addWidget(self._info_label(_tr("mutation_planner.single_trait.no_pairs")))
        else:
            pair_table = QTableWidget(len(pairs), 4)
            pair_table.setHorizontalHeaderLabels([
                _tr("mutation_planner.multi_trait.table.parent_a"),
                _tr("mutation_planner.multi_trait.table.parent_b"),
                _tr("mutation_planner.single_trait.table.note"),
                _tr("mutation_planner.multi_trait.table.inbreeding"),
            ])
            pair_table.verticalHeader().setVisible(False)
            pair_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            pair_table.setSelectionMode(QAbstractItemView.NoSelection)
            pair_table.setMaximumHeight(min(30 + len(pairs) * 26, 400))
            pair_table.setStyleSheet(
                "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; font-size:11px; }"
            )
            phh = pair_table.horizontalHeader()
            phh.setSectionResizeMode(0, QHeaderView.Stretch)
            phh.setSectionResizeMode(1, QHeaderView.Stretch)
            phh.setSectionResizeMode(2, QHeaderView.Stretch)
            phh.setSectionResizeMode(3, QHeaderView.Interactive)
            pair_table.setColumnWidth(3, 80)
            for row, (ca, cb, note) in enumerate(pairs):
                pair_table.setItem(row, 0, QTableWidgetItem(ca.name))
                pair_table.setItem(row, 1, QTableWidgetItem(cb.name))
                pair_table.setItem(row, 2, QTableWidgetItem(note))
                pair_risk = risk_percent(ca, cb)
                risk_pct = int(round(pair_risk))
                inbred_item = QTableWidgetItem(f"{risk_pct}%")
                inbred_item.setTextAlignment(Qt.AlignCenter)
                if risk_pct >= 100:
                    inbred_item.setForeground(QColor("#d97777"))
                elif risk_pct >= 50:
                    inbred_item.setForeground(QColor("#d8b56a"))
                elif risk_pct >= 20:
                    inbred_item.setForeground(QColor("#8fc9e6"))
                pair_table.setItem(row, 3, inbred_item)
            layout.addWidget(pair_table)

        layout.addStretch()

    def _filtered_cats(self) -> list[Cat]:
        room_filter = self._room_combo.currentData() or ""
        trait_filters = list(self._browse_trait_datas)
        result = []
        for cat in self._alive_cats:
            if room_filter and cat.room != room_filter:
                continue
            if trait_filters and not any(_cat_has_trait(cat, category, trait_key) for category, trait_key in trait_filters):
                continue
            result.append(cat)
        return result

    def _refresh_table(self):
        self._cat_table.setSortingEnabled(False)
        cats = self._filtered_cats()
        self._cat_table.setRowCount(len(cats))
        for row, cat in enumerate(cats):
            name_item = QTableWidgetItem(cat.name)
            name_item.setData(Qt.UserRole, id(cat))
            icon = _make_tag_icon(_cat_tags(cat), dot_size=10, spacing=3)
            if not icon.isNull():
                name_item.setIcon(icon)
            self._cat_table.setItem(row, 0, name_item)

            gender_item = QTableWidgetItem(cat.gender_display if hasattr(cat, 'gender_display') else cat.gender)
            gender_item.setTextAlignment(Qt.AlignCenter)
            self._cat_table.setItem(row, 1, gender_item)

            age_item = _SortByUserRoleItem(str(cat.age) if cat.age is not None else "\u2014")
            age_item.setData(Qt.UserRole, cat.age if cat.age is not None else -1)
            age_item.setTextAlignment(Qt.AlignCenter)
            self._cat_table.setItem(row, 2, age_item)

            stat_sum = sum(cat.base_stats.values()) if cat.base_stats else 0
            sum_item = _SortByUserRoleItem(str(stat_sum))
            sum_item.setData(Qt.UserRole, stat_sum)
            sum_item.setTextAlignment(Qt.AlignCenter)
            self._cat_table.setItem(row, 3, sum_item)

            muts = ", ".join(_mutation_display_name(m) for m in cat.mutations) if cat.mutations else "\u2014"
            self._cat_table.setItem(row, 4, QTableWidgetItem(muts))

            passives = ", ".join(_mutation_display_name(p) for p in cat.passive_abilities) if cat.passive_abilities else "\u2014"
            self._cat_table.setItem(row, 5, QTableWidgetItem(passives))

            abils = ", ".join(_mutation_display_name(a) for a in cat.abilities) if cat.abilities else "\u2014"
            self._cat_table.setItem(row, 6, QTableWidgetItem(abils))
        self._cat_table.setSortingEnabled(True)

    def _on_stim_changed(self):
        if len(self._selected_pair) == 2:
            self._update_outcome_panel(self._selected_pair[0], self._selected_pair[1])
        elif self._active_trait_data is not None:
            self._update_trait_detail_panel(self._active_trait_data)
        self._save_session_state()

    def _on_selection_changed(self):
        rows = sorted(set(idx.row() for idx in self._cat_table.selectionModel().selectedRows()))
        cats_by_id = {id(c): c for c in self._cats}
        selected: list[Cat] = []
        for r in rows:
            item = self._cat_table.item(r, 0)
            if item is None:
                continue
            cat_id = item.data(Qt.UserRole)
            cat = cats_by_id.get(cat_id)
            if cat is not None:
                selected.append(cat)

        if len(selected) == 2:
            self._selected_pair = selected
            self._pair_label.setText(f"Pair: {selected[0].name} \u00d7 {selected[1].name}")
            self._pair_label.setStyleSheet("color:#8fb8a0; font-size:11px; font-weight:bold;")
            self._update_outcome_panel(selected[0], selected[1])
            self._session_state["last_mode"] = "pair"
            self._save_session_state()
        elif len(selected) == 1:
            self._selected_pair = selected
            self._pair_label.setText(_tr("mutation_planner.selected_one", name=selected[0].name))
            self._pair_label.setStyleSheet("color:#aa8; font-size:11px;")
            self._clear_outcome_panel()
            self._save_session_state()
        else:
            self._selected_pair.clear()
            self._pair_label.setText(_tr("mutation_planner.pair_hint"))
            self._pair_label.setStyleSheet("color:#666; font-size:11px;")
            self._clear_outcome_panel()
            self._save_session_state()

    def _clear_outcome_panel(self):
        layout = self._outcome_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._outcome_placeholder = QLabel(_tr("mutation_planner.outcome.placeholder_pair"))
        self._outcome_placeholder.setStyleSheet("color:#555; font-size:12px;")
        self._outcome_placeholder.setWordWrap(True)
        layout.addWidget(self._outcome_placeholder)
        layout.addStretch()

    def _sec_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#7d8bb0; font-size:13px; font-weight:bold; padding:4px 0 2px 0;")
        return lbl

    def _info_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#bbb; font-size:11px;")
        lbl.setWordWrap(True)
        return lbl

    def _update_outcome_panel(self, cat_a: Cat, cat_b: Cat):
        layout = self._outcome_layout
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        stim = self._stim_spin.value()
        favor_weight = _stimulation_inheritance_weight(stim)

        # ── Header ──
        layout.addWidget(self._sec_label(
            f"{cat_a.name} \u00d7 {cat_b.name}"
        ))

        # ── Top summary strip: stats table + pair context ──
        stat_table = QTableWidget(7, 4)
        stat_table.setHorizontalHeaderLabels([
            _tr("mutation_planner.pair.table.stat"),
            cat_a.name,
            cat_b.name,
            _tr("mutation_planner.pair.table.offspring_likely"),
        ])
        stat_table.verticalHeader().setVisible(False)
        stat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        stat_table.setSelectionMode(QAbstractItemView.NoSelection)
        stat_table.setMaximumHeight(30 + 7 * 26)
        stat_table.setStyleSheet(
            "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; font-size:11px; }"
        )
        shh = stat_table.horizontalHeader()
        shh.setSectionResizeMode(0, QHeaderView.Interactive)
        shh.setSectionResizeMode(1, QHeaderView.Interactive)
        shh.setSectionResizeMode(2, QHeaderView.Interactive)
        shh.setSectionResizeMode(3, QHeaderView.Stretch)
        stat_table.setColumnWidth(0, 40)
        stat_table.setColumnWidth(1, 60)
        stat_table.setColumnWidth(2, 60)

        for row, stat_name in enumerate(STAT_NAMES):
            a_val = cat_a.base_stats.get(stat_name, 0)
            b_val = cat_b.base_stats.get(stat_name, 0)
            if a_val == b_val:
                likely = f"{a_val} (same)"
            elif a_val > b_val:
                likely = f"{a_val} ({favor_weight*100:.0f}%) or {b_val} ({(1-favor_weight)*100:.0f}%)"
            else:
                likely = f"{b_val} ({favor_weight*100:.0f}%) or {a_val} ({(1-favor_weight)*100:.0f}%)"

            stat_table.setItem(row, 0, QTableWidgetItem(stat_name))
            a_item = QTableWidgetItem(str(a_val))
            a_item.setTextAlignment(Qt.AlignCenter)
            stat_table.setItem(row, 1, a_item)
            b_item = QTableWidgetItem(str(b_val))
            b_item.setTextAlignment(Qt.AlignCenter)
            stat_table.setItem(row, 2, b_item)
            stat_table.setItem(row, 3, QTableWidgetItem(likely))

        stat_table.setToolTip(
            _tr("mutation_planner.pair.stat_summary", favor=f"{favor_weight*100:.1f}", stim=stim)
        )

        pair_context = QFrame()
        pair_context.setStyleSheet("QFrame { background:#0e0e20; border:1px solid #26264a; border-radius:4px; }")
        pair_context_layout = QVBoxLayout(pair_context)
        pair_context_layout.setContentsMargins(10, 8, 10, 8)
        pair_context_layout.setSpacing(4)

        pair_context_layout.addWidget(self._sec_label(_tr("mutation_planner.pair.partners", default="Partners")))
        pair_context_layout.addWidget(self._info_label(
            f"Partner A: {cat_a.name} ({cat_a.gender_display})\n"
            f"Partner B: {cat_b.name} ({cat_b.gender_display})"
        ))
        pair_context_layout.addWidget(self._sec_label(
            _tr("mutation_planner.pair.offspring_side", default="Likely offspring")
        ))
        pair_context_layout.addWidget(self._info_label(
            _tr("mutation_planner.pair.stat_summary", favor=f"{favor_weight*100:.1f}", stim=stim)
        ))

        top_strip = QWidget()
        top_strip_layout = QHBoxLayout(top_strip)
        top_strip_layout.setContentsMargins(0, 0, 0, 0)
        top_strip_layout.setSpacing(10)
        top_strip_layout.addWidget(stat_table, 2)
        top_strip_layout.addWidget(pair_context, 1)
        layout.addWidget(top_strip)

        # ── Disorder Inheritance ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.pair.disorder_inheritance")))
        layout.addWidget(self._info_label(
            _tr("mutation_planner.pair.disorder_summary")
        ))

        a_disorders = cat_a.disorders or []
        b_disorders = cat_b.disorders or []

        disorder_rows: list[str] = []
        seen = set()
        for disorder in a_disorders:
            name = _mutation_display_name(disorder)
            key = disorder.lower()
            if key not in seen:
                seen.add(key)
                # Check if other parent also has it
                b_has = any(other.lower() == key for other in b_disorders)
                if b_has:
                    pct = 1.0 - (0.85 * 0.85)  # both parents: ~27.75%
                    disorder_rows.append(f"  {name}: {pct*100:.1f}% (both parents)")
                else:
                    disorder_rows.append(f"  {name}: 15% (from {cat_a.name})")
        for disorder in b_disorders:
            key = disorder.lower()
            if key not in seen:
                seen.add(key)
                name = _mutation_display_name(disorder)
                disorder_rows.append(f"  {name}: 15% (from {cat_b.name})")

        if disorder_rows:
            layout.addWidget(self._info_label("\n".join(disorder_rows)))
        else:
            layout.addWidget(self._info_label(_tr("mutation_planner.pair.no_disorders")))

        # Birth defect risk breakdown
        coi = kinship_coi(cat_a, cat_b)
        disorder_ch, part_defect_ch, combined_ch = _malady_breakdown(coi)
        inbred_note = ""
        if cat_a.inbredness is None and cat_b.inbredness is None:
            inbred_note = _tr("mutation_planner.pair.inbred_note_unknown")
        layout.addWidget(self._info_label(
            _tr(
                "mutation_planner.pair.risk_breakdown",
                disorder=f"{disorder_ch*100:.1f}",
                part=f"{part_defect_ch*100:.1f}",
                combined=f"{combined_ch*100:.1f}",
                note=inbred_note,
            )
        ))

        note_lbl = QLabel(_tr("mutation_planner.pair.note"))
        note_lbl.setStyleSheet("color:#665; font-size:10px; font-style:italic;")
        note_lbl.setWordWrap(True)
        layout.addWidget(note_lbl)
        # ── Visual Mutation Inheritance ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.pair.visual_mutation_inheritance")))
        layout.addWidget(self._info_label(
            _tr("mutation_planner.pair.visual_summary", stim=stim, favor=f"{favor_weight*100:.1f}")
        ))
        # Since 1.1, birth defects roll with effective stim = stim - 2 x inbreeding%,
        # so defect rows use a separate (worse) inheritance weight for inbred pairs.
        defect_weight = _defect_inheritance_weight(stim, coi)
        if coi > 0.0:
            layout.addWidget(self._info_label(
                _tr(
                    "mutation_planner.pair.defect_stim_note",
                    default=("Birth defects: inbreeding ({coi}%) reduces effective stimulation to "
                             "{eff} for defect inheritance rolls — defect rows below use {chance}%."),
                    coi=f"{coi*100:.0f}",
                    eff=f"{stim - 2.0 * coi * 100.0:.0f}",
                    chance=f"{defect_weight*100:.0f}",
                )
            ))

        # Group mutations by group_key
        a_by_group: dict[str, list[dict]] = {}
        for entry in (cat_a.visual_mutation_entries or []):
            gk = entry.get("group_key", "")
            a_by_group.setdefault(gk, []).append(entry)
        b_by_group: dict[str, list[dict]] = {}
        for entry in (cat_b.visual_mutation_entries or []):
            gk = entry.get("group_key", "")
            b_by_group.setdefault(gk, []).append(entry)

        all_groups = sorted(set(list(a_by_group.keys()) + list(b_by_group.keys())))
        if all_groups:
            mut_table = QTableWidget(len(all_groups), 4)
            mut_table.setHorizontalHeaderLabels([
                _tr("mutation_planner.pair.table.body_part"),
                cat_a.name,
                cat_b.name,
                _tr("mutation_planner.pair.table.odds"),
            ])
            mut_table.verticalHeader().setVisible(False)
            mut_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            mut_table.setSelectionMode(QAbstractItemView.NoSelection)
            mut_table.setMaximumHeight(min(30 + len(all_groups) * 26, 300))
            mut_table.setStyleSheet(
                "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; font-size:11px; }"
            )
            mhh = mut_table.horizontalHeader()
            mhh.setSectionResizeMode(0, QHeaderView.Interactive)
            mhh.setSectionResizeMode(1, QHeaderView.Stretch)
            mhh.setSectionResizeMode(2, QHeaderView.Stretch)
            mhh.setSectionResizeMode(3, QHeaderView.Interactive)
            mut_table.setColumnWidth(0, 100)
            mut_table.setColumnWidth(3, 120)

            for row, gk in enumerate(all_groups):
                a_entries = a_by_group.get(gk, [])
                b_entries = b_by_group.get(gk, [])
                part_label = a_entries[0].get("part_label", gk) if a_entries else (
                    b_entries[0].get("part_label", gk) if b_entries else gk
                )
                a_names = ", ".join(e.get("name", "?") for e in a_entries) or _tr("mutation_planner.pair.base")
                b_names = ", ".join(e.get("name", "?") for e in b_entries) or _tr("mutation_planner.pair.base")

                a_has_mutation = bool(a_entries)
                b_has_mutation = bool(b_entries)

                if a_has_mutation and b_has_mutation:
                    if a_names == b_names:
                        odds_text = _tr("mutation_planner.pair.odds.same_mutation")
                    else:
                        odds_text = _tr("mutation_planner.pair.odds.split", a=cat_a.name, b=cat_b.name)
                elif a_has_mutation:
                    w = defect_weight if all(e.get("is_defect") for e in a_entries) else favor_weight
                    odds_text = _tr("mutation_planner.pair.odds.mutated", name=cat_a.name, chance=f"{w*100:.0f}")
                elif b_has_mutation:
                    w = defect_weight if all(e.get("is_defect") for e in b_entries) else favor_weight
                    odds_text = _tr("mutation_planner.pair.odds.mutated", name=cat_b.name, chance=f"{w*100:.0f}")
                else:
                    odds_text = _tr("mutation_planner.pair.odds.none")

                mut_table.setItem(row, 0, QTableWidgetItem(part_label))
                mut_table.setItem(row, 1, QTableWidgetItem(a_names))
                mut_table.setItem(row, 2, QTableWidgetItem(b_names))
                mut_table.setItem(row, 3, QTableWidgetItem(odds_text))

            layout.addWidget(mut_table)
        else:
            layout.addWidget(self._info_label(_tr("mutation_planner.pair.no_visual_mutations")))

        # ── Passive Inheritance ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.pair.passive_ability_inheritance")))
        passive_chance = 0.05 + 0.01 * stim
        spell_chance = 0.2 + 0.025 * stim
        layout.addWidget(self._info_label(
            _tr(
                "mutation_planner.pair.passive_spell_summary",
                passive=f"{min(passive_chance, 1.0)*100:.1f}",
                spell=f"{min(spell_chance, 1.0)*100:.1f}",
            )
        ))

        a_passives = list(getattr(cat_a, "passive_abilities", []) or [])
        b_passives = list(getattr(cat_b, "passive_abilities", []) or [])
        if a_passives or b_passives:
            chips, share_a, share_b = _inheritance_candidates(
                a_passives, b_passives, stim, _mutation_display_name,
            )
            passive_lines = []
            for label, tip in chips:
                passive_lines.append(f"  {label}")
            if passive_lines:
                layout.addWidget(self._info_label(
                    _tr("mutation_planner.pair.passive_weighted_prefix") +
                    "\n" +
                    "\n".join(passive_lines)
                ))

        a_spells = [x for x in (cat_a.abilities or []) if not is_basic_attack_token(x)]
        b_spells = [x for x in (cat_b.abilities or []) if not is_basic_attack_token(x)]
        if a_spells or b_spells:
            spell_chips, _, _ = _inheritance_candidates(
                a_spells, b_spells,
                stim, _mutation_display_name,
            )
            spell_lines = []
            for label, tip in spell_chips:
                spell_lines.append(f"  {label}")
            if spell_lines:
                layout.addWidget(self._info_label(
                    _tr("mutation_planner.pair.spell_weighted_prefix") +
                    "\n" +
                    "\n".join(spell_lines)
                ))

        # ── Lineage Info ──
        layout.addWidget(self._sec_label(_tr("mutation_planner.pair.lineage")))
        lineage_lines = []
        for label, cat in [(cat_a.name, cat_a), (cat_b.name, cat_b)]:
            pa_name = cat.parent_a.name if cat.parent_a else _tr("common.unknown", default="Unknown")
            pb_name = cat.parent_b.name if cat.parent_b else _tr("common.unknown", default="Unknown")
            inbred_str = f"{cat.inbredness:.2f}" if cat.inbredness is not None else "?"
            lineage_lines.append(f"{label}: parents = {pa_name} \u00d7 {pb_name}, inbreeding = {inbred_str}")

            # Show grandparent disorders if available
            for gp_label, gp in [("  GP", cat.parent_a), ("  GP", cat.parent_b)]:
                if gp is not None and gp.passive_abilities:
                    gp_passives = ", ".join(_mutation_display_name(p) for p in gp.passive_abilities)
                    lineage_lines.append(f"    {gp.name} passives: {gp_passives}")

        layout.addWidget(self._info_label("\n".join(lineage_lines)))

        layout.addStretch()
