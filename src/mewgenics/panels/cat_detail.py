"""CatDetailPanel, LineageDialog, and chip helper widgets."""
import re
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QGridLayout, QPushButton, QSpinBox, QSizePolicy,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QToolButton, QMenu,
)
from PySide6.QtCore import Qt, Signal, QTimer, QItemSelectionModel
from PySide6.QtGui import QColor, QBrush, QFont, QFontMetrics, QPixmap

from save_parser import (
    Cat, STAT_NAMES,
    can_breed, risk_percent, kinship_coi,
    get_parents, get_grandparents, find_common_ancestors,
    _appearance_group_names, _appearance_preview_text,
    _inheritance_candidates,
    _malady_breakdown,
)
from breeding import (
    pair_projection, score_pair as score_pair_factors,
    game_compatibility, breeding_success_chance,
    ability_inheritance_chances, disorder_inheritance_chances,
)
from mewgenics.constants import (
    STAT_COLORS, PAIR_COLORS,
    COL_BL, COL_MB,
    _CHIP_STYLE, _DEFECT_CHIP_STYLE, _NAME_STYLE, _META_STYLE,
    _WARN_STYLE, _SAFE_STYLE, _ANCS_STYLE, _PANEL_BG, _DETAIL_TEXT_STYLE, _NOTE_STYLE,
)
from mewgenics.utils.localization import _tr
from mewgenics.utils.config import _load_app_config, _save_app_config, _saved_stat_icon_mode
from mewgenics.utils.cat_analysis import _cat_base_sum, _pair_breakpoint_analysis
from mewgenics.utils.calibration import _trait_label_from_value, _trait_level_color
from mewgenics.utils.abilities import (
    _mutation_display_name, _ability_display_name, _ability_tip, _ability_upgraded_tip, _strip_tier,
    _ability_effect_lines, _mutation_effect_lines,
    _mutation_effect_components,
    _trait_inheritance_probabilities,
)
from mewgenics.utils.ability_icons import (
    get_ability_icon_pixmap as _ability_icon_pixmap,
    get_passive_icon_pixmap as _passive_icon_pixmap,
)
from mewgenics.utils.game_data import _GPAK_PATH
from mewgenics.utils.tags import _game_tag_color, _game_tag_tooltip
from mewgenics.utils.styling import (
    _chip, _upgraded_chip, _defect_chip, _sec, _vsep, _hsep,
    _detail_text_block, _enforce_min_font_in_widget_tree,
)


def _wrapped_chip_block(items, tooltip_fn=None, display_fn=None, max_per_row: int = 5) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    if not items:
        return box
    for start in range(0, len(items), max_per_row):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        for item in items[start:start + max_per_row]:
            is_upgraded = False
            if isinstance(item, tuple) and len(item) == 3:
                text, tip, is_upgraded = item
                tip = tip or (tooltip_fn(text) if tooltip_fn else "")
            elif isinstance(item, tuple):
                text, tip = item
                tip = tip or (tooltip_fn(text) if tooltip_fn else "")
            else:
                text = display_fn(item) if display_fn else item
                tip = tooltip_fn(item) if tooltip_fn else ""
            chip = _upgraded_chip(text, tip) if is_upgraded else _chip(text, tip)
            row.addWidget(chip)
        row.addStretch()
        layout.addLayout(row)
    return box


def _breakable(text: str) -> str:
    """Insert zero-width spaces before uppercase letters in camelCase so
    QLabel word-wrap can break long single-word ability names."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', '\u200b', text)


class ChipRow(QWidget):
    _STACKED_ICON_MIN = 72
    _STACKED_ICON_MAX = 72

    def __init__(self, items, tooltip_fn=None, display_fn=None, icon_fn=None, defect: bool = False, icon_size: int | None = None):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        text_font = QFont()
        text_font.setPixelSize(11)
        metrics = QFontMetrics(text_font)

        # Pre-compute a uniform icon size: the widest label wins, then
        # every chip uses the same square so they all line up.
        resolved: list[tuple[str, str, bool]] = []  # (text, tip, is_upgraded)
        for item in items:
            is_upgraded = False
            if isinstance(item, tuple) and len(item) == 3:
                text, tip, is_upgraded = item
                tip = tip or (tooltip_fn(text) if tooltip_fn else "")
            elif isinstance(item, tuple):
                text, tip = item
                tip = tip or (tooltip_fn(text) if tooltip_fn else "")
            else:
                text = display_fn(item) if display_fn else item
                tip = tooltip_fn(item) if tooltip_fn else ""
            resolved.append((str(text), tip, bool(is_upgraded)))
        uniform_size = min(
            self._STACKED_ICON_MAX,
            max(self._STACKED_ICON_MIN, *(metrics.horizontalAdvance(t) for t, _, _ in resolved)),
        )

        for idx, item in enumerate(items):
            text, tip, is_upgraded = resolved[idx]

            pixmap = None
            if icon_fn is not None:
                try:
                    pixmap = icon_fn(item if not isinstance(item, tuple) else item[0], uniform_size)
                except Exception:
                    pixmap = None

            if pixmap is not None and not pixmap.isNull():
                chip = QFrame()
                chip.setObjectName("abilityChip")
                chip.setStyleSheet(
                    "QFrame#abilityChip { background:#252545; color:#ccc; border-radius:6px;"
                    " padding:4px 7px; font-size:11px; }"
                    if not defect else
                    "QFrame#abilityChip { background:#3a1a1a; color:#e0a0a0; border-radius:6px;"
                    " padding:4px 7px; font-size:11px; }"
                )
                chip_col = QVBoxLayout(chip)
                chip_col.setContentsMargins(0, 0, 0, 0)
                chip_col.setSpacing(2)
                icon_lbl = QLabel()
                _dpr = getattr(QApplication.instance(), "devicePixelRatio", lambda: 1.0)()
                _phys = int(uniform_size * _dpr)
                _scaled = pixmap.scaled(_phys, _phys, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                _scaled.setDevicePixelRatio(_dpr)
                icon_lbl.setPixmap(_scaled)
                icon_lbl.setFixedSize(uniform_size, uniform_size)
                icon_lbl.setAlignment(Qt.AlignCenter)
                icon_lbl.setStyleSheet("background:transparent;")
                text_lbl = QLabel(_breakable(text))
                text_lbl.setAlignment(Qt.AlignCenter)
                text_lbl.setWordWrap(True)
                text_lbl.setFixedWidth(uniform_size)
                text_lbl.setStyleSheet(
                    "background:transparent; color:#ccc; font-size:11px;"
                    if not defect else
                    "background:transparent; color:#e0a0a0; font-size:11px;"
                )
                chip_col.addWidget(icon_lbl, 0, Qt.AlignHCenter)
                chip_col.addWidget(text_lbl, 0, Qt.AlignHCenter)
                if tip:
                    chip.setToolTip(tip)
                    icon_lbl.setToolTip(tip)
                    text_lbl.setToolTip(tip)
                row.addWidget(chip, 0, Qt.AlignTop)
            else:
                if defect:
                    row.addWidget(_defect_chip(text, tip), 0, Qt.AlignTop)
                elif is_upgraded:
                    row.addWidget(_upgraded_chip(text, tip), 0, Qt.AlignTop)
                else:
                    row.addWidget(_chip(text, tip), 0, Qt.AlignTop)
        row.addStretch()


def _defect_chip_row(items, tooltip_fn=None) -> QWidget:
    """Like ChipRow but uses the reddish defect chip style."""
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(5)
    for item in items:
        if isinstance(item, tuple):
            text, tip = item
            tip = tip or (tooltip_fn(text) if tooltip_fn else "")
        else:
            text = item
            tip = tooltip_fn(item) if tooltip_fn else ""
        row.addWidget(_defect_chip(text, tip))
    row.addStretch()
    return w


def _mutation_delta_chip(label: str, amount: str) -> QLabel:
    pos = str(amount or "").strip().startswith("+")
    bg = "#183820" if pos else "#3a1818"
    fg = "#d8f5d8" if pos else "#f3d7d7"
    chip = QLabel(f"{label} {amount}")
    chip.setStyleSheet(
        f"QLabel {{ background:{bg}; color:{fg}; border:1px solid {'#315b41' if pos else '#6b3838'};"
        " border-radius:6px; padding:2px 7px; font-size:11px; font-weight:bold; }}"
    )
    chip.setToolTip(f"{label} {amount}")
    return chip


def _mutation_card(text: str, tip: str, defect: bool = False) -> QWidget:
    summary, effects, affects = _mutation_effect_components(tip)
    card = QWidget()
    card.setObjectName("mutationCard")
    card.setStyleSheet(
        "QWidget#mutationCard { background:#101024; border:1px solid #1e1e38; border-radius:4px; }"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(6, 4, 6, 4)
    layout.setSpacing(3)

    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(5)
    top.addWidget(_defect_chip(text, tip) if defect else _chip(text, tip))
    if effects:
        for label, amount in effects:
            top.addWidget(_mutation_delta_chip(label, amount))
    else:
        top.addWidget(_chip(_tr("cat_detail.no_stat_change", default="No stat change")))
    top.addStretch()
    layout.addLayout(top)

    note_parts: list[str] = []
    if summary and not summary.lower().startswith("affects:"):
        note_parts.append(summary)
    if affects:
        note_parts.append(_tr("cat_detail.affects", default="Affects: {slots}", slots=", ".join(affects)))
    if note_parts:
        note = QLabel("  |  ".join(note_parts))
        note.setWordWrap(True)
        note.setStyleSheet("color:#8a8aa5; font-size:10px;")
        layout.addWidget(note)

    card.setToolTip(tip)
    return card


def _mutation_cards_block(items, defect: bool = False) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    for text, tip in items:
        layout.addWidget(_mutation_card(text, tip, defect=defect))
    layout.addStretch()
    return box


def _game_tag_badge(text: str) -> QLabel:
    tag_text = str(text or "").strip()
    badge = QLabel(tag_text)
    color = QColor(_game_tag_color(tag_text))
    fg = "#111111" if color.lightness() >= 140 else "#f5f7ff"
    badge.setStyleSheet(
        f"color:{fg}; background:{color.name()}; border:1px solid {color.darker(140).name()};"
        " border-radius:2px; padding:1px 6px; font-size:10px; font-weight:bold;"
    )
    badge.setToolTip(_game_tag_tooltip(tag_text) or _tr("cat_detail.game_tag", default="Game tag from save file"))
    badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return badge


class CatDetailPanel(QWidget):
    """
    Bottom panel driven by table selection.
    1 cat  → abilities / mutations / ancestry
    2 cats → breeding comparison with lineage safety check
    """

    @property
    def current_cats(self) -> list[Cat]:
        return self._current_cats

    def __init__(self):
        super().__init__()
        self.setStyleSheet(_PANEL_BG)
        self.setFixedHeight(0)
        self._show_lineage: bool = False
        self._pair_stimulation: int = int(_load_app_config().get("pair_stimulation", 50) or 50)
        self._current_cats: list[Cat] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { border:none; background:#0a0a18; }")
        self._content = QWidget()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

    def set_show_lineage(self, show: bool):
        self._show_lineage = show

    def show_cats(self, cats: list[Cat]):
        self._current_cats = list(cats)
        self._content = QWidget()
        self._scroll.setWidget(self._content)

        if not cats:
            self.setFixedHeight(0)
            return

        min_h = 160 if len(cats) == 1 else 220
        self.setMinimumHeight(min_h)
        self.setMaximumHeight(16777215)   # remove the fixed-height lock

        if len(cats) == 1:
            self._build_single(cats[0])
        else:
            self._build_pair(cats[0], cats[1])
        _enforce_min_font_in_widget_tree(self)

    # ── Single cat ─────────────────────────────────────────────────────────

    def _build_single(self, cat: Cat):
        root = QHBoxLayout(self._content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(20)

        # Identity
        id_col = QVBoxLayout()
        id_col.setSpacing(3)
        name_row = QHBoxLayout()
        nl = QLabel(cat.name); nl.setStyleSheet(_NAME_STYLE)
        gl = QLabel(cat.gender_display)
        gl.setStyleSheet("color:#7ac; font-size:12px; font-weight:bold;")
        name_row.addWidget(nl); name_row.addWidget(gl); name_row.addStretch()
        if getattr(cat, "name_tag", ""):
            name_row.addWidget(_game_tag_badge(str(cat.name_tag).strip()))
        id_col.addLayout(name_row)

        id_col.addWidget(QLabel(cat.room_display or "—", styleSheet=_META_STYLE))

        # Stats: compact grid with shared Base / Mod / Total row labels.
        id_col.addSpacing(4)
        stats_box = QWidget()
        stats_box.setStyleSheet("background:#101024; border:1px solid #1e1e38; border-radius:4px;")
        stats_grid = QGridLayout(stats_box)
        stats_grid.setContentsMargins(6, 4, 6, 4)
        stats_grid.setHorizontalSpacing(6)
        stats_grid.setVerticalSpacing(1)
        stats_box.setMinimumWidth(280)

        corner = QLabel("")
        corner.setStyleSheet("color:#888; font-size:9px;")
        stats_grid.addWidget(corner, 0, 0)
        stats_grid.setColumnMinimumWidth(0, 34)

        show_stat_icons = _saved_stat_icon_mode()
        for col, stat_name in enumerate(STAT_NAMES, start=1):
            if show_stat_icons:
                from mewgenics.models.cat_table_model import _stat_svg_pixmap
                pix = _stat_svg_pixmap(stat_name, 18)
                if pix is not None:
                    head = QLabel()
                    head.setPixmap(pix)
                    head.setAlignment(Qt.AlignCenter)
                    head.setToolTip(stat_name)
                else:
                    head = QLabel(stat_name)
                    head.setStyleSheet("color:#888; font-size:9px; font-weight:bold;")
                    head.setAlignment(Qt.AlignCenter)
            else:
                head = QLabel(stat_name)
                head.setStyleSheet("color:#888; font-size:9px; font-weight:bold;")
                head.setAlignment(Qt.AlignCenter)
            stats_grid.addWidget(head, 0, col)
            stats_grid.setColumnMinimumWidth(col, 28)

        for row, label in enumerate((_tr("cat_detail.base"), _tr("cat_detail.mod"), _tr("cat_detail.total")), start=1):
            row_lbl = QLabel(label)
            row_lbl.setStyleSheet("color:#777; font-size:9px; font-weight:bold;")
            stats_grid.addWidget(row_lbl, row, 0)

        for col, stat_name in enumerate(STAT_NAMES, start=1):
            base = cat.base_stats[stat_name]
            total = cat.total_stats[stat_name]
            delta = total - base
            delta_sign = "+" if delta > 0 else ""
            delta_color = "#5a9" if delta > 0 else ("#c55" if delta < 0 else "#888")
            base_bg = STAT_COLORS.get(base, QColor(45, 45, 60)).name()
            total_bg = STAT_COLORS.get(total, QColor(45, 45, 60)).name()

            base_lbl = QLabel(str(base))
            base_lbl.setStyleSheet(
                f"background:{base_bg}; color:#fff; font-size:9px; font-weight:bold;"
                "border-radius:3px; padding:1px 4px;"
            )
            base_lbl.setAlignment(Qt.AlignCenter)
            stats_grid.addWidget(base_lbl, 1, col)

            mod_lbl = QLabel(f"{delta_sign}{delta}")
            mod_lbl.setStyleSheet(
                f"background:{'#183820' if delta > 0 else ('#3a1818' if delta < 0 else '#101024')};"
                f"color:{delta_color}; font-size:9px; border-radius:3px; padding:1px 4px;"
            )
            mod_lbl.setAlignment(Qt.AlignCenter)
            stats_grid.addWidget(mod_lbl, 2, col)

            total_lbl = QLabel(str(total))
            total_lbl.setStyleSheet(
                f"background:{total_bg}; color:#fff; font-size:9px; font-weight:bold;"
                "border-radius:3px; padding:1px 4px;"
            )
            total_lbl.setAlignment(Qt.AlignCenter)
            stats_grid.addWidget(total_lbl, 3, col)

        id_col.addWidget(stats_box)

        # Attributes: quick-read combat traits that matter for adventure cats.
        id_col.addWidget(_sec("ATTRIBUTES"))
        attr_box = QWidget()
        attr_box.setStyleSheet("background:#101024; border:1px solid #1e1e38; border-radius:4px;")
        attr_grid = QGridLayout(attr_box)
        attr_grid.setContentsMargins(6, 4, 6, 4)
        attr_grid.setHorizontalSpacing(6)
        attr_grid.setVerticalSpacing(4)
        attr_box.setMinimumWidth(280)

        def _attr_chip(label: str, value: str, color: QColor, tooltip: str) -> QLabel:
            chip = QLabel(f"{label}: {value}")
            fg = "#111111" if color.lightness() >= 140 else "#f5f7ff"
            chip.setStyleSheet(
                f"background:{color.name()}; color:{fg}; font-size:9px; font-weight:bold;"
                "border-radius:3px; padding:2px 5px;"
            )
            chip.setAlignment(Qt.AlignCenter)
            chip.setToolTip(tooltip)
            return chip

        aggression_label = _trait_label_from_value("aggression", cat.aggression) or "unknown"
        libido_label = _trait_label_from_value("libido", cat.libido) or "unknown"
        inbred_label = _trait_label_from_value("inbredness", cat.inbredness) or "unknown"
        sexuality_raw = str(getattr(cat, "sexuality", "") or "").strip() or "unknown"
        sexuality_label = sexuality_raw.title() if sexuality_raw != "unknown" else "Unknown"
        sexuality_color = QColor(72, 100, 140) if sexuality_raw != "unknown" else QColor(80, 80, 95)

        attr_specs = [
            (
                0,
                0,
                "Aggression",
                aggression_label.title(),
                _trait_level_color(aggression_label),
                f"Aggression: {cat.aggression:.3f} ({aggression_label})" if cat.aggression is not None else "Aggression: unknown",
            ),
            (
                0,
                1,
                "Libido",
                libido_label.title(),
                _trait_level_color(libido_label),
                f"Libido: {cat.libido:.3f} ({libido_label})" if cat.libido is not None else "Libido: unknown",
            ),
            (
                1,
                0,
                "Inbredness",
                inbred_label.title(),
                _trait_level_color(inbred_label),
                f"Inbredness: {cat.inbredness:.3f} ({inbred_label})" if cat.inbredness is not None else "Inbredness: unknown",
            ),
            (
                1,
                1,
                "Sexuality",
                sexuality_label,
                sexuality_color,
                f"Sexuality: {sexuality_raw}",
            ),
        ]
        for row, col, label, value, color, tooltip in attr_specs:
            attr_grid.addWidget(_attr_chip(label, value, color, tooltip), row, col)

        id_col.addWidget(attr_box)

        def _navigate(target: Cat):
            mw = self.window()
            # Use "All Cats" view so gone/adventure cats are always reachable
            mw._filter("__all__", mw._btn_everyone)
            for row in range(mw._source_model.rowCount()):
                if mw._source_model.cat_at(row) is target:
                    proxy_idx = mw._proxy_model.mapFromSource(
                        mw._source_model.index(row, 0))
                    if proxy_idx.isValid():
                        mw._table.selectionModel().setCurrentIndex(
                            proxy_idx,
                            QItemSelectionModel.SelectionFlag.ClearAndSelect |
                            QItemSelectionModel.SelectionFlag.Rows)
                        mw._table.scrollTo(proxy_idx)
                    break

        if self._show_lineage:
            tree_btn = QPushButton(_tr("cat_detail.family_tree"))
            tree_btn.setStyleSheet(
                "QPushButton { color:#5a8aaa; background:transparent; border:1px solid #252545;"
                " padding:3px 8px; border-radius:4px; font-size:10px; }"
                "QPushButton:hover { background:#131328; }")
            tree_btn.clicked.connect(lambda: LineageDialog(cat, self, navigate_fn=_navigate).exec())
            id_col.addWidget(tree_btn)

        # Blacklist toggle button
        blacklist_btn = QPushButton(_tr("cat_detail.include_in_breeding") if not cat.is_blacklisted else _tr("cat_detail.exclude_from_breeding"))
        blacklist_btn.setStyleSheet(
            "QPushButton { color:#888; background:transparent; border:1px solid #252545;"
            " padding:3px 8px; border-radius:4px; font-size:10px; }"
            "QPushButton:hover { background:#131328; color:#ddd; }")
        def _toggle_blacklist():
            cat.is_blacklisted = not cat.is_blacklisted
            if cat.is_blacklisted:
                cat.must_breed = False
            blacklist_btn.setText(_tr("cat_detail.include_in_breeding") if not cat.is_blacklisted else _tr("cat_detail.exclude_from_breeding"))
            must_breed_btn.setText(_tr("cat_detail.must_breed") if cat.must_breed else _tr("cat_detail.normal_priority"))
            mw = self.window()
            if hasattr(mw, "_source_model") and mw._source_model is not None:
                for row in range(mw._source_model.rowCount()):
                    if mw._source_model.cat_at(row) is cat:
                        idx_bl = mw._source_model.index(row, COL_BL)
                        idx_mb = mw._source_model.index(row, COL_MB)
                        mw._source_model.dataChanged.emit(idx_bl, idx_bl, [Qt.DisplayRole, Qt.CheckStateRole, Qt.ToolTipRole])
                        mw._source_model.dataChanged.emit(idx_mb, idx_mb, [Qt.DisplayRole, Qt.CheckStateRole, Qt.ToolTipRole])
                        # Emit blacklistChanged which will trigger _on_blacklist_changed
                        mw._source_model.blacklistChanged.emit()
                        break
        blacklist_btn.clicked.connect(_toggle_blacklist)
        id_col.addWidget(blacklist_btn)

        # Must breed toggle button
        must_breed_btn = QPushButton(_tr("cat_detail.must_breed") if cat.must_breed else _tr("cat_detail.normal_priority"))
        must_breed_btn.setStyleSheet(
            "QPushButton { color:#888; background:transparent; border:1px solid #252545;"
            " padding:3px 8px; border-radius:4px; font-size:10px; }"
            "QPushButton:hover { background:#131328; color:#ddd; }")
        def _toggle_must_breed():
            cat.must_breed = not cat.must_breed
            if cat.must_breed:
                cat.is_blacklisted = False
            must_breed_btn.setText(_tr("cat_detail.must_breed") if cat.must_breed else _tr("cat_detail.normal_priority"))
            blacklist_btn.setText(_tr("cat_detail.include_in_breeding") if not cat.is_blacklisted else _tr("cat_detail.exclude_from_breeding"))
            mw = self.window()
            if hasattr(mw, "_source_model") and mw._source_model is not None:
                for row in range(mw._source_model.rowCount()):
                    if mw._source_model.cat_at(row) is cat:
                        idx_bl = mw._source_model.index(row, COL_BL)
                        idx_mb = mw._source_model.index(row, COL_MB)
                        mw._source_model.dataChanged.emit(idx_bl, idx_bl, [Qt.DisplayRole, Qt.CheckStateRole, Qt.ToolTipRole])
                        mw._source_model.dataChanged.emit(idx_mb, idx_mb, [Qt.DisplayRole, Qt.CheckStateRole, Qt.ToolTipRole])
                        # Emit blacklistChanged to save must_breed state
                        mw._source_model.blacklistChanged.emit()
                        break
        must_breed_btn.clicked.connect(_toggle_must_breed)
        id_col.addWidget(must_breed_btn)

        id_col.addStretch()
        root.addLayout(id_col)

        # Abilities
        if cat.abilities or cat.passive_abilities or cat.disorders:
            root.addWidget(_vsep())
            ab = QVBoxLayout(); ab.setSpacing(4)
            passive_tiers = getattr(cat, "passive_tiers", {})
            ab.addWidget(_sec("ABILITIES"))
            ability_items = [
                (_ability_display_name(base) if tier == 1 else f"{_ability_display_name(base)}+",
                 _ability_upgraded_tip(name),
                 tier > 1)
                for name in cat.abilities
                for base, tier in [_strip_tier(name)]
            ]
            ab.addWidget(ChipRow(ability_items, icon_fn=_ability_icon_pixmap))
            if cat.passive_abilities:
                ab.addWidget(_sec("PASSIVE"))
                passive_items = [
                    (f"● {_mutation_display_name(name)}" if tier == 1
                     else f"● {_mutation_display_name(name)}+",
                     _ability_upgraded_tip(name, passive_tier=tier),
                     tier > 1)
                    for name in cat.passive_abilities
                    for tier in [passive_tiers.get(name, 1)]
                ]
                ab.addWidget(ChipRow(passive_items, icon_fn=_passive_icon_pixmap))
            if cat.disorders:
                ab.addWidget(_sec("DISORDERS"))
                ab.addWidget(ChipRow(
                    cat.disorders,
                    tooltip_fn=_ability_tip,
                    display_fn=lambda n: f"⚠ {_mutation_display_name(n)}",
                    icon_fn=_passive_icon_pixmap,
                    defect=True,
                ))
            ability_lines = _ability_effect_lines(cat)
            if ability_lines:
                ab.addWidget(_detail_text_block(ability_lines))
            elif not _GPAK_PATH:
                ab.addWidget(_detail_text_block(
                    ["Ability descriptions unavailable. Set MEWGENICS_GPAK_PATH or place resources.gpak next to the app."],
                    style=_NOTE_STYLE,
                ))
            ab.addStretch()
            root.addLayout(ab)

        # Mutations
        if cat.mutations or cat.defects:
            root.addWidget(_vsep())
            mu = QVBoxLayout(); mu.setSpacing(4)
            if cat.mutations:
                mu.addWidget(_sec("MUTATIONS"))
                mu.addWidget(_mutation_cards_block(cat.mutation_chip_items))
            if cat.defects:
                mu.addWidget(_sec("BIRTH DEFECTS"))
                mu.addWidget(_mutation_cards_block(cat.defect_chip_items, defect=True))
            mu.addStretch()
            root.addLayout(mu)

        # Equipment
        if cat.equipment:
            root.addWidget(_vsep())
            eq = QVBoxLayout(); eq.setSpacing(4)
            eq.addWidget(_sec("EQUIPMENT"))
            eq.addWidget(ChipRow(cat.equipment))
            eq.addStretch()
            root.addLayout(eq)

        # Ancestry
        parents = get_parents(cat)
        gparents = get_grandparents(cat)
        repaired = bool(getattr(cat, "pedigree_was_repaired", False))
        if parents or repaired:
            root.addWidget(_vsep())
            anc = QVBoxLayout(); anc.setSpacing(4)
            anc.addWidget(_sec("LINEAGE"))

            if parents:
                source_text = " × ".join(f"{p.name} ({p.gender_display})" for p in parents)
            else:
                source_text = _tr("cat_detail.stray", default="Stray")
            if repaired:
                source_text += f" ({_tr('cat_detail.pedigree_repaired', default='pedigree repaired')})"

            source_lbl = QLabel(source_text)
            source_lbl.setStyleSheet(_ANCS_STYLE)
            if repaired:
                source_lbl.setToolTip(
                    _tr(
                        "cat_detail.pedigree_repaired_note",
                        default="One or more parent links were broken while loading this save to prevent a pedigree cycle.",
                    )
                )
            anc.addWidget(source_lbl)

            if gparents:
                gp_names = "  ·  ".join(gp.short_name for gp in gparents)
                gl2 = QLabel(gp_names)
                gl2.setStyleSheet("color:#555; font-size:10px;")
                anc.addWidget(gl2)

            anc.addStretch()
            root.addLayout(anc)

        # Lovers & haters
        if cat.lovers or cat.haters:
            root.addWidget(_vsep())
            rel = QVBoxLayout(); rel.setSpacing(4)
            if cat.lovers:
                rel.addWidget(_sec("LOVERS"))
                rel.addWidget(ChipRow([c.name for c in cat.lovers]))
            if cat.haters:
                rel.addWidget(_sec("HATERS"))
                hl = ChipRow([c.name for c in cat.haters])
                for i in range(hl.layout().count() - 1):  # tint hater chips red
                    w = hl.layout().itemAt(i).widget()
                    if w:
                        w.setStyleSheet(w.styleSheet().replace("background:#252545", "background:#452020"))
                rel.addWidget(hl)
            rel.addStretch()
            root.addLayout(rel)

        root.addStretch()

    # ── Breeding pair ──────────────────────────────────────────────────────

    def _build_pair(self, a: Cat, b: Cat):
        ok, reason = can_breed(a, b)

        root = QVBoxLayout(self._content)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(10)

        # ── Header: parent names + room ────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        for cat in (a, b):
            nl = QLabel(cat.name)
            nl.setStyleSheet(_NAME_STYLE)
            nl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            hdr.addWidget(nl)
            gl = QLabel(cat.gender_display)
            gl.setStyleSheet("color:#7ac; font-size:12px; font-weight:bold;")
            hdr.addWidget(gl)
            if getattr(cat, "name_tag", ""):
                hdr.addWidget(_game_tag_badge(str(cat.name_tag).strip()))
            rl = QLabel(f"  {cat.room_display}" if cat.room_display else "")
            rl.setStyleSheet(_META_STYLE)
            hdr.addWidget(rl)
            if cat is not b:
                x = QLabel("×")
                x.setStyleSheet("color:#444; font-size:14px; padding:0 10px;")
                hdr.addWidget(x)

        hdr.addStretch()
        stim_lbl = QLabel(_tr("cat_detail.stimulation"))
        stim_lbl.setStyleSheet(_META_STYLE)
        hdr.addWidget(stim_lbl)
        stim_box = QSpinBox()
        stim_box.setRange(-100, 200)
        stim_box.setValue(max(-100, min(200, int(self._pair_stimulation))))
        stim_box.setFixedWidth(64)
        stim_box.setStyleSheet(
            "QSpinBox { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:2px 6px; font-size:11px; }"
        )
        def _set_pair_stimulation(value: int):
            self._pair_stimulation = int(value)
            data = _load_app_config()
            data["pair_stimulation"] = self._pair_stimulation
            _save_app_config(data)
            if len(self._current_cats) >= 2:
                current_pair = list(self._current_cats[:2])
                QTimer.singleShot(0, lambda pair=current_pair: self.show_cats(pair))
        stim_box.valueChanged.connect(_set_pair_stimulation)
        hdr.addWidget(stim_box)
        if not ok:
            hdr.addWidget(QLabel(f"⚠  {reason}", styleSheet=_WARN_STYLE))

        root.addLayout(hdr)

        if not ok:
            root.addStretch()
            return

        # ── Stats grid + abilities ─────────────────────────────────────────
        mid = QHBoxLayout()
        mid.setSpacing(20)

        # Grid rows: Cat A, Cat B, then Offspring last
        grid_rows = [
            (a, True),    # (cat, is_cat)
            (b, True),
            (None, False),  # offspring range
        ]

        grid_w = QWidget()
        grid   = QGridLayout(grid_w)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnMinimumWidth(0, 110)   # ensure label column has room for full names

        # Stat column headers
        show_stat_icons = _saved_stat_icon_mode()
        for j, stat in enumerate(STAT_NAMES):
            if show_stat_icons:
                from mewgenics.models.cat_table_model import _stat_svg_pixmap
                pix = _stat_svg_pixmap(stat, 18)
                if pix is not None:
                    h = QLabel()
                    h.setPixmap(pix)
                    h.setAlignment(Qt.AlignCenter)
                    h.setToolTip(stat)
                else:
                    h = QLabel(stat)
                    h.setStyleSheet("color:#555; font-size:9px; font-weight:bold;")
                    h.setAlignment(Qt.AlignCenter)
            else:
                h = QLabel(stat)
                h.setStyleSheet("color:#555; font-size:9px; font-weight:bold;")
                h.setAlignment(Qt.AlignCenter)
            grid.addWidget(h, 0, j + 1)
        sum_col = len(STAT_NAMES) + 1
        sh = QLabel(_tr("cat_detail.sum"))
        sh.setStyleSheet("color:#455; font-size:9px; font-weight:bold;")
        sh.setAlignment(Qt.AlignCenter)
        grid.addWidget(sh, 0, sum_col)

        for i, (cat, is_cat) in enumerate(grid_rows):
            row_num = i + 1

            # Label cell: name + gender chip for cat rows, plain text for offspring
            lbl_w  = QWidget()
            lbl_hb = QHBoxLayout(lbl_w)
            lbl_hb.setContentsMargins(0, 0, 6, 0)
            lbl_hb.setSpacing(5)

            if is_cat:
                name_lbl = QLabel(cat.name)
                name_lbl.setStyleSheet("color:#ddd; font-size:11px; font-weight:bold;")
                gen_lbl  = QLabel(cat.gender_display)
                gen_lbl.setFixedWidth(20)
                gen_lbl.setAlignment(Qt.AlignCenter)
                gen_lbl.setStyleSheet(
                    "color:#fff; background:#253555; border-radius:4px;"
                    " font-size:10px; font-weight:bold;")
                lbl_hb.addWidget(name_lbl)
                lbl_hb.addWidget(gen_lbl)
            else:
                off_lbl = QLabel(_tr("cat_detail.offspring"))
                off_lbl.setStyleSheet("color:#555; font-size:10px; font-style:italic;")
                lbl_hb.addWidget(off_lbl)

            lbl_hb.addStretch()
            grid.addWidget(lbl_w, row_num, 0)

            # Stat cells
            for j, stat in enumerate(STAT_NAMES):
                if is_cat:
                    val  = cat.base_stats[stat]
                    c    = STAT_COLORS.get(val, QColor(100, 100, 115))
                    cell = QLabel(str(val))
                    cell.setAlignment(Qt.AlignCenter)
                    cell.setStyleSheet(
                        f"background:rgb({c.red()},{c.green()},{c.blue()});"
                        f"color:#fff; font-size:11px; font-weight:bold;"
                        f"border-radius:2px; padding:2px 6px;")
                else:
                    va, vb = a.base_stats[stat], b.base_stats[stat]
                    lo, hi = min(va, vb), max(va, vb)
                    c      = STAT_COLORS.get(hi, QColor(100, 100, 115))
                    text   = f"{lo}–{hi}" if lo != hi else str(lo)
                    cell   = QLabel(text)
                    cell.setAlignment(Qt.AlignCenter)
                    cell.setStyleSheet(
                        f"color:rgb({c.red()},{c.green()},{c.blue()});"
                        f"font-size:11px; font-weight:bold;")
                grid.addWidget(cell, row_num, j + 1)

            # Sum cell
            if is_cat:
                sv = sum(cat.base_stats.values())
                sc = QLabel(str(sv))
                sc.setStyleSheet("color:#aaa; font-size:11px; font-weight:bold;")
            else:
                lo_s = sum(min(a.base_stats[st], b.base_stats[st]) for st in STAT_NAMES)
                hi_s = sum(max(a.base_stats[st], b.base_stats[st]) for st in STAT_NAMES)
                sc = QLabel(f"{lo_s}–{hi_s}" if lo_s != hi_s else str(lo_s))
                sc.setStyleSheet("color:#777; font-size:11px; font-weight:bold;")
            sc.setAlignment(Qt.AlignCenter)
            grid.addWidget(sc, row_num, sum_col)

        mid.addWidget(grid_w)
        mid.addWidget(_vsep())

        # Inherited personality traits (based on parsed/calibrated parent values)
        trait_col = QVBoxLayout()
        trait_col.setSpacing(6)
        trait_col.addWidget(_sec("INHERITED TRAITS"))

        def _trait_text(field: str, value) -> str:
            label = _trait_label_from_value(field, value)
            return label if label else "unknown"

        def _offspring_trait_text(field: str, va, vb) -> str:
            if va is None or vb is None:
                return "unknown"
            lo = min(float(va), float(vb))
            hi = max(float(va), float(vb))
            lo_label = _trait_label_from_value(field, lo) or "unknown"
            hi_label = _trait_label_from_value(field, hi) or "unknown"
            if lo_label == hi_label:
                return lo_label
            return f"{lo_label} to {hi_label}"

        def _trait_chip(text: str) -> QLabel:
            chip = _chip(text)
            color = _trait_level_color(text)
            chip.setStyleSheet(
                f"QLabel {{ background:rgb({color.red()},{color.green()},{color.blue()}); "
                f"color:#fff; border-radius:6px; padding:2px 7px; font-size:11px; }}"
            )
            return chip

        for field, title in (
            ("aggression", "Aggression"),
            ("libido", "Libido"),
            ("inbredness", "Inbredness"),
        ):
            va = getattr(a, field, None)
            vb = getattr(b, field, None)
            row = QHBoxLayout()
            row.setSpacing(5)
            row.addWidget(QLabel(f"{title}:", styleSheet="color:#555; font-size:10px;"))
            row.addWidget(_trait_chip(_trait_text(field, va)))
            row.addWidget(QLabel("x", styleSheet="color:#444; font-size:10px;"))
            row.addWidget(_trait_chip(_trait_text(field, vb)))
            row.addWidget(QLabel("->", styleSheet="color:#666; font-size:10px;"))
            row.addWidget(_trait_chip(_offspring_trait_text(field, va, vb)))
            row.addStretch()
            trait_col.addLayout(row)

        trait_col.addStretch()
        mid.addLayout(trait_col)
        mid.addWidget(_vsep())

        # Abilities column
        ab_col = QVBoxLayout()
        ab_col.setSpacing(6)
        ab_col.addWidget(_sec("ABILITIES"))
        for cat in (a, b):
            if cat.abilities or cat.passive_abilities or cat.disorders:
                ab_col.addWidget(QLabel(f"{cat.name}:", styleSheet="color:#555; font-size:10px;"))
                _pt = getattr(cat, "passive_tiers", {})
                ability_items = [
                    (_ability_display_name(base) if tier == 1 else f"{_ability_display_name(base)}+",
                     _ability_upgraded_tip(ab),
                     tier > 1)
                    for ab in cat.abilities
                    for base, tier in [_strip_tier(ab)]
                ]
                ability_items.extend(
                    (f"● {_mutation_display_name(pa)}" if _pt.get(pa, 1) == 1
                     else f"● {_mutation_display_name(pa)}+",
                     _ability_upgraded_tip(pa, passive_tier=_pt.get(pa, 1)),
                     _pt.get(pa, 1) > 1)
                    for pa in cat.passive_abilities
                )
                ability_items.extend(
                    (f"⚠ {_mutation_display_name(d)}", _ability_tip(d), False)
                    for d in cat.disorders
                )
                ab_col.addWidget(_wrapped_chip_block(ability_items, max_per_row=4))
        ab_col.addStretch()
        mid.addLayout(ab_col)
        mid.addWidget(_vsep())

        if a.mutations or b.mutations or a.defects or b.defects:
            mu_col = QVBoxLayout()
            mu_col.setSpacing(6)
            if a.mutations or b.mutations:
                mu_col.addWidget(_sec("MUTATIONS"))
                for cat in (a, b):
                    if cat.mutations:
                        mu_col.addWidget(QLabel(f"{cat.name}:", styleSheet="color:#555; font-size:10px;"))
                        mu_col.addWidget(_mutation_cards_block(cat.mutation_chip_items))
            if a.defects or b.defects:
                mu_col.addWidget(_sec("BIRTH DEFECTS"))
                for cat in (a, b):
                    if cat.defects:
                        mu_col.addWidget(QLabel(f"{cat.name}:", styleSheet="color:#555; font-size:10px;"))
                        mu_col.addWidget(_mutation_cards_block(cat.defect_chip_items, defect=True))
            mu_col.addStretch()
            mid.addLayout(mu_col)

        root.addLayout(mid)

        stim = float(self._pair_stimulation)
        active_candidates, share_a, share_b = _inheritance_candidates(
            list(a.abilities),
            list(b.abilities),
            stim,
        )
        passive_candidates, _, _ = _inheritance_candidates(
            list(a.passive_abilities),
            list(b.passive_abilities),
            stim,
            display_fn=_mutation_display_name,
        )
        breakpoint_info = _pair_breakpoint_analysis(a, b, stim)

        inh = QVBoxLayout()
        inh.setSpacing(6)
        inh.addWidget(_sec("INHERITANCE"))
        inh_note = QLabel(
            f"Estimated at stimulation {int(stim)}. Parent source weighting: "
            f"{a.name} {share_a * 100:.0f}% / {b.name} {share_b * 100:.0f}%."
        )
        inh_note.setStyleSheet(_META_STYLE)
        inh_note.setWordWrap(True)
        inh.addWidget(inh_note)

        # ── Ability inheritance chances ──
        ab_chances = ability_inheritance_chances(stim)
        active_pct = ab_chances["first_active"] * 100
        active2_pct = ab_chances["second_active"] * 100
        passive_pct = ab_chances["passive"] * 100

        active_label = QLabel(
            f"Active spell candidates  ({active_pct:.0f}% first, {active2_pct:.0f}% second)",
            styleSheet="color:#555; font-size:10px;",
        )
        inh.addWidget(active_label)
        if active_candidates:
            inh.addWidget(_wrapped_chip_block(active_candidates, max_per_row=5))
        else:
            inh.addWidget(QLabel("No active ability candidates.", styleSheet=_META_STYLE))

        passive_label = QLabel(
            f"Passive candidates  ({passive_pct:.0f}% chance)",
            styleSheet="color:#555; font-size:10px;",
        )
        inh.addWidget(passive_label)
        if passive_candidates:
            inh.addWidget(_wrapped_chip_block(passive_candidates, max_per_row=4))
        else:
            inh.addWidget(QLabel("No passive candidates.", styleSheet=_META_STYLE))

        # ── Trait inheritance probabilities ──
        trait_probs = _trait_inheritance_probabilities(a, b, stim)
        if trait_probs:
            inh.addWidget(QLabel(_tr("cat_detail.trait_inheritance"), styleSheet="color:#555; font-size:10px;"))
            prob_chips: list[tuple[str, str]] = []
            for display, category, prob, detail in trait_probs:
                pct = prob * 100
                cat_label = {"ability": _tr("cat_detail.spell"), "passive": _tr("cat_detail.passive"), "mutation": _tr("cat_detail.mutation")}.get(category, category)
                chip_text = f"{display} {pct:.0f}%"
                tip_text = f"[{cat_label}] {detail}\n{_ability_tip(display)}" if _ability_tip(display) else f"[{cat_label}] {detail}"
                prob_chips.append((chip_text, tip_text))
            inh.addWidget(_wrapped_chip_block(prob_chips, max_per_row=5))

        # ── Compatibility estimate ──
        compat = game_compatibility(a, b)
        compat_row = QHBoxLayout()
        compat_row.setSpacing(8)
        compat_row.addWidget(QLabel("Compatibility:", styleSheet="color:#555; font-size:10px;"))
        compat_val = f"{compat:.2f}"
        if compat < 0.05:
            compat_bg = "#6a2a2a"
            compat_note = "will not breed"
        elif compat < 0.15:
            compat_bg = "#5a4a2a"
            compat_note = "low"
        elif compat < 0.40:
            compat_bg = "#3a3a2a"
            compat_note = "moderate"
        else:
            compat_bg = "#2a3a2a"
            compat_note = "high"
        compat_chip = _chip(f"{compat_val} ({compat_note})")
        compat_chip.setStyleSheet(
            f"QLabel {{ background:{compat_bg}; color:#ddd; border-radius:6px;"
            f" padding:2px 7px; font-size:11px; }}")
        compat_row.addWidget(compat_chip)
        success = breeding_success_chance(compat)
        if success > 0:
            success_chip = _chip(f"~{success*100:.1f}% success/attempt")
            success_chip.setStyleSheet(
                "QLabel { background:#1a2a3a; color:#8ab; border-radius:6px;"
                " padding:2px 7px; font-size:11px; }")
            compat_row.addWidget(success_chip)
        compat_tip = QLabel("(?)")
        compat_tip.setStyleSheet("color:#555; font-size:10px;")
        compat_tip.setToolTip(
            "Game formula: 0.15 × CHA × Libido × Lover × Sexuality\n"
            "Pairs below 0.05 are rejected by the game.\n"
            "Success chance = compat² × (1 + 0.1 × comfort)"
        )
        compat_row.addWidget(compat_tip)
        compat_row.addStretch()
        inh.addLayout(compat_row)

        # ── Risk breakdown ──
        coi = kinship_coi(a, b)
        disorder_ch, part_defect_ch, combined_ch = _malady_breakdown(coi)
        risk_row = QHBoxLayout()
        risk_row.setSpacing(8)
        risk_row.addWidget(QLabel("Risk:", styleSheet="color:#555; font-size:10px;"))

        def _risk_chip(text: str, value: float) -> QLabel:
            c = _chip(text)
            if value > 0.10:
                bg = "#6a2a2a"
            elif value > 0.03:
                bg = "#5a4a2a"
            else:
                bg = "#2a3a2a"
            c.setStyleSheet(
                f"QLabel {{ background:{bg}; color:#ddd; border-radius:6px;"
                f" padding:2px 7px; font-size:11px; }}")
            return c

        risk_row.addWidget(_risk_chip(f"Inbred disorder {disorder_ch*100:.1f}%", disorder_ch))
        risk_row.addWidget(_risk_chip(f"Part defect {part_defect_ch*100:.1f}%", part_defect_ch))
        risk_row.addWidget(_risk_chip(f"Combined {combined_ch*100:.1f}%", combined_ch))

        # ── Disorder inheritance from parents ──
        dis_info = disorder_inheritance_chances(a, b)
        if dis_info["chance_any"] > 0:
            dis_chips: list[str] = []
            if dis_info["disorders_a"]:
                dis_chips.append(f"15% from {a.name} ({', '.join(dis_info['disorders_a'])})")
            if dis_info["disorders_b"]:
                dis_chips.append(f"15% from {b.name} ({', '.join(dis_info['disorders_b'])})")
            risk_row.addWidget(QLabel("|", styleSheet="color:#333; font-size:10px;"))
            for dt in dis_chips:
                dc = _chip(dt)
                dc.setStyleSheet(
                    "QLabel { background:#4a3a2a; color:#dda; border-radius:6px;"
                    " padding:2px 7px; font-size:11px; }")
                risk_row.addWidget(dc)

        disorder_tip = QLabel("(?)")
        disorder_tip.setStyleSheet("color:#555; font-size:10px;")
        disorder_tip.setToolTip(
            "Inbred disorder: base 2%, scales above 0.20 CoI\n"
            "Part defect: 0 below 0.05 CoI, then 1.5× CoI\n"
            "Combined: chance of at least one inbred issue\n"
            "Parent disorders: 15% chance from each parent independently"
        )
        risk_row.addWidget(disorder_tip)
        risk_row.addStretch()
        inh.addLayout(risk_row)

        root.addLayout(inh)

        # ── Breakpoints + appearance + lineage ─────────────────────────────
        bot = QHBoxLayout()
        bot.setSpacing(20)

        bp_col = QVBoxLayout()
        bp_col.setSpacing(6)
        bp_col.addWidget(_sec("BREAKPOINT HINTS"))
        bp_note = QLabel(
            f"{breakpoint_info['headline']}  |  "
            f"Sum range {breakpoint_info['sum_range'][0]}-{breakpoint_info['sum_range'][1]}  |  "
            f"Expected avg {breakpoint_info['avg_expected']:.1f}"
        )
        bp_note.setStyleSheet(_DETAIL_TEXT_STYLE)
        bp_note.setWordWrap(True)
        bp_col.addWidget(bp_note)

        bp_table = QTableWidget(4, len(STAT_NAMES))
        bp_table.setHorizontalHeaderLabels(STAT_NAMES)
        bp_table.setVerticalHeaderLabels(["Range", "Exp", "Breakpoint", "Hint"])
        bp_table.setSelectionMode(QAbstractItemView.NoSelection)
        bp_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        bp_table.setFocusPolicy(Qt.NoFocus)
        bp_table.setWordWrap(False)
        bp_table.setStyleSheet("""
            QTableWidget {
                background:#0d0d1c; alternate-background-color:#131326;
                color:#ddd; border:1px solid #26264a; font-size:11px;
            }
            QTableWidget::item { padding:2px 4px; }
            QHeaderView::section {
                background:#16213e; color:#888; padding:4px 3px;
                border:none; border-bottom:1px solid #1e1e38;
                border-right:1px solid #16213e; font-size:10px; font-weight:bold;
            }
        """)
        bp_hh = bp_table.horizontalHeader()
        for col in range(len(STAT_NAMES)):
            bp_hh.setSectionResizeMode(col, QHeaderView.Stretch)
        bp_vh = bp_table.verticalHeader()
        for row in range(4):
            bp_vh.setSectionResizeMode(row, QHeaderView.ResizeToContents)
        for col_idx, row in enumerate(breakpoint_info["rows"]):
            status_color = {
                "locked": QColor(98, 194, 135),
                "can hit 7": QColor(143, 201, 230),
                "one step off": QColor(216, 181, 106),
                "stalled": QColor(190, 145, 40),
            }.get(row["status"], QColor(120, 120, 135))
            range_item = QTableWidgetItem(f"{row['lo']}-{row['hi']}" if row["lo"] != row["hi"] else str(row["lo"]))
            exp_item = QTableWidgetItem(f"{row['expected']:.1f}")
            status_item = QTableWidgetItem(row["status"])
            hint_text = (
                "lock" if row["status"] == "locked"
                else "7 now" if row["status"] == "can hit 7"
                else "next up" if row["status"] == "one step off"
                else "needs help"
            )
            hint_item = QTableWidgetItem(hint_text)
            for item in (range_item, exp_item, status_item, hint_item):
                item.setForeground(QBrush(status_color))
                item.setTextAlignment(Qt.AlignCenter)
            bp_table.setItem(0, col_idx, range_item)
            bp_table.setItem(1, col_idx, exp_item)
            bp_table.setItem(2, col_idx, status_item)
            bp_table.setItem(3, col_idx, hint_item)
        bp_table.resizeRowsToContents()
        bp_height = bp_table.horizontalHeader().height() + 4
        for row in range(bp_table.rowCount()):
            bp_height += bp_table.rowHeight(row)
        bp_height += 4
        bp_table.setFixedHeight(bp_height)
        bp_col.addWidget(bp_table)
        if breakpoint_info["hints"]:
            hints_lbl = QLabel("  |  ".join(breakpoint_info["hints"][:2]))
            hints_lbl.setStyleSheet(_META_STYLE)
            hints_lbl.setWordWrap(True)
            bp_col.addWidget(hints_lbl)
        bot.addLayout(bp_col, 2)
        bot.addWidget(_vsep())

        app_col = QVBoxLayout()
        app_col.setSpacing(6)
        app_col.addWidget(_sec("APPEARANCE PREVIEW"))
        app_note = QLabel(_tr("cat_detail.appearance_preview"))
        app_note.setStyleSheet(_META_STYLE)
        app_note.setWordWrap(True)
        app_col.addWidget(app_note)

        appearance_groups = [
            ("fur", _tr("cat_detail.appearance.fur")),
            ("body", _tr("cat_detail.appearance.body")),
            ("head", _tr("cat_detail.appearance.head")),
            ("tail", _tr("cat_detail.appearance.tail")),
            ("ears", _tr("cat_detail.appearance.ears")),
            ("eyes", _tr("cat_detail.appearance.eyes")),
            ("mouth", _tr("cat_detail.appearance.mouth")),
        ]
        shown_preview = False
        for group_key, title in appearance_groups:
            a_names = _appearance_group_names(a, group_key)
            b_names = _appearance_group_names(b, group_key)
            if not a_names and not b_names:
                continue
            shown_preview = True
            row = QHBoxLayout()
            row.setSpacing(5)
            row.addWidget(QLabel(f"{title}:", styleSheet="color:#555; font-size:10px;"))
            row.addWidget(_chip(" / ".join(a_names) if a_names else "Base"))
            row.addWidget(QLabel("x", styleSheet="color:#444; font-size:10px;"))
            row.addWidget(_chip(" / ".join(b_names) if b_names else "Base"))
            row.addWidget(QLabel("->", styleSheet="color:#666; font-size:10px;"))
            row.addWidget(_chip(_appearance_preview_text(a_names, b_names)))
            row.addStretch()
            app_col.addLayout(row)

        if not shown_preview:
            app_col.addWidget(QLabel(_tr("cat_detail.no_appearance_data"), styleSheet=_META_STYLE))

        app_col.addStretch()
        bot.addLayout(app_col, 1)
        if self._show_lineage:
            bot.addWidget(_vsep())

        if self._show_lineage:
            lc = QVBoxLayout()
            lc.setSpacing(3)
            lc.addWidget(_sec("LINEAGE"))
            common    = find_common_ancestors(a, b)
            is_direct = (a in get_parents(b) or b in get_parents(a))
            is_haters = (b in getattr(a, 'haters', []) or a in getattr(b, 'haters', []))

            if is_haters:
                lc.addWidget(QLabel("⚠  These cats hate each other", styleSheet=_WARN_STYLE))
            if is_direct:
                lc.addWidget(QLabel("⚠  Direct parent/offspring", styleSheet=_WARN_STYLE))
            elif common:
                lc.addWidget(QLabel(
                    f"⚠  {len(common)} shared ancestor{'s' if len(common) > 1 else ''}: "
                    + "  ·  ".join(c.short_name for c in common[:6]),
                    styleSheet=_WARN_STYLE))
            elif get_parents(a) or get_parents(b):
                lc.addWidget(QLabel("✓  No shared ancestors", styleSheet=_SAFE_STYLE))
            else:
                lc.addWidget(QLabel("—  Lineage unknown", styleSheet=_META_STYLE))

            lc.addStretch()
            bot.addLayout(lc)
        bot.addStretch()

        root.addLayout(bot)


# ── Lineage tree dialog ───────────────────────────────────────────────────────

class LineageDialog(QDialog):
    """
    Family tree dialog — generations from oldest (top) to newest (bottom).
    Layout:  Grandparents → Parents → Self → Children → Grandchildren
    """

    def __init__(self, cat: 'Cat', parent=None, navigate_fn=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("family_tree.title", name=cat.name))
        self.setMinimumSize(700, 400)
        self.setStyleSheet(
            "QDialog { background:#0a0a18; }"
            "QScrollArea { border:none; background:#0a0a18; }"
            "QPushButton { background:#1e1e38; color:#ccc; border:1px solid #2a2a4a;"
            " padding:5px 14px; border-radius:4px; font-size:11px; }"
            "QPushButton:hover { background:#252555; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(12)

        # ── Reusable box builder ─────────────────────────────────────────
        def cat_box(cat_obj, highlight=False, dim=False):
            if cat_obj is None:
                btn = QPushButton(_tr("family_tree.unknown"))
                btn.setEnabled(False)
                btn.setStyleSheet(
                    "QPushButton { color:#252535; font-size:10px; padding:6px 10px;"
                    " background:#0d0d1c; border:1px solid #141424; border-radius:5px; }")
            else:
                line2 = cat_obj.gender_display
                if cat_obj.room_display:
                    line2 += f"  {cat_obj.room_display}"
                bg     = "#1a2840" if highlight else ("#0e0e1a" if dim else "#121222")
                border = "#3060a0" if highlight else ("#1a1a28" if dim else "#222238")
                col    = "#ddd"    if not dim    else "#333"
                can_nav = navigate_fn is not None and cat_obj is not cat
                hover  = "#1d3560" if can_nav else bg
                btn = QPushButton(f"{cat_obj.name}\n{line2}")
                btn.setStyleSheet(
                    f"QPushButton {{ color:{col}; font-size:10px; padding:6px 10px;"
                    f" background:{bg}; border:1px solid {border}; border-radius:5px;"
                    f" text-align:center; }}"
                    f"QPushButton:hover {{ background:{hover}; }}")
                if can_nav:
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.clicked.connect(
                        lambda checked=False, c=cat_obj: (self.accept(), navigate_fn(c)))
            btn.setMinimumWidth(100)
            btn.setMaximumWidth(200)
            return btn

        # ── Generation label ─────────────────────────────────────────────
        def gen_row_label(text):
            lbl = QLabel(text)
            # letter-spacing is not a Qt QSS property — apply via QFont.
            lbl.setStyleSheet(
                "color:#333; font-size:9px; font-weight:bold;"
                " min-width:90px;")
            f = lbl.font()
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
            lbl.setFont(f)
            lbl.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            return lbl

        def make_gen_row(label_text, cat_list, highlight_all=False, dim_all=False):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(gen_row_label(label_text))
            for c in cat_list:
                row.addWidget(cat_box(c, highlight=highlight_all,
                                      dim=(dim_all and c is not None)))
            row.addStretch()
            outer.addLayout(row)

        # ── Build generations ────────────────────────────────────────────
        pa, pb = cat.parent_a, cat.parent_b
        gp_a1 = pa.parent_a if pa else None
        gp_a2 = pa.parent_b if pa else None
        gp_b1 = pb.parent_a if pb else None
        gp_b2 = pb.parent_b if pb else None

        grandparents = [gp_a1, gp_a2, gp_b1, gp_b2]
        parents      = [pa, pb]

        children = list(cat.children)
        grandchildren: list = []
        for child in children:
            grandchildren.extend(child.children)

        make_gen_row(_tr("family_tree.grandparents"), grandparents)
        make_gen_row(_tr("family_tree.parents"),      parents)
        make_gen_row("",             [cat], highlight_all=True)
        if children:
            make_gen_row(_tr("family_tree.lineage_children"), children[:8])
            if len(children) > 8:
                outer.addWidget(
                    QLabel(_tr("family_tree.more_children", count=len(children)-8),
                           styleSheet="color:#444; font-size:10px; padding-left:100px;"))
        if grandchildren:
            unique_gc = list({id(g): g for g in grandchildren}.values())
            make_gen_row(_tr("family_tree.lineage_grandchildren"), unique_gc[:8])
            if len(unique_gc) > 8:
                outer.addWidget(
                    QLabel(_tr("family_tree.more_grandchildren", count=len(unique_gc)-8),
                           styleSheet="color:#444; font-size:10px; padding-left:100px;"))

        outer.addStretch()
        close_btn = QPushButton(_tr("family_tree.close"))
        close_btn.clicked.connect(self.accept)
        outer.addWidget(close_btn, alignment=Qt.AlignRight)
        _enforce_min_font_in_widget_tree(self)
