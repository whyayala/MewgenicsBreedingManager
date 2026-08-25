"""FurnitureView — dedicated view for furniture placement and room stat totals."""

import html
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QHeaderView,
    QAbstractItemView, QSplitter, QFrame, QLineEdit,
    QTableWidget, QTableWidgetItem, QTextBrowser,
    QPushButton, QToolButton,
)
from PySide6.QtCore import Qt, QSize, QTimer, QByteArray, QItemSelectionModel
from PySide6.QtGui import QColor, QBrush

from save_parser import (
    Cat, FurnitureItem, FurnitureDefinition, FurnitureRoomSummary,
    build_furniture_room_summaries,
    FURNITURE_ROOM_STAT_KEYS, FURNITURE_ROOM_STAT_LABELS,
)

from mewgenics.utils.localization import _tr, ROOM_DISPLAY
from mewgenics.utils.config import _load_ui_state, _save_ui_state
from mewgenics.utils.styling import _enforce_min_font_in_widget_tree
from mewgenics.utils.tags import _make_pin_icon
from mewgenics.models.cat_table_model import _SortByUserRoleItem


class FurnitureView(QWidget):
    """Dedicated view for furniture placement and current room stat totals."""

    _WHOLE_HOME_KEY = "__whole_home__"

    _ROOM_ORDER = {
        "Attic": 0,
        "Floor2_Small": 1,
        "Floor2_Large": 2,
        "Floor1_Large": 3,
        "Floor1_Small": 4,
    }

    _STAT_ACCENTS = {
        "Appeal": "#d8b25e",
        "Comfort": "#68c7cf",
        "Stimulation": "#8f8fff",
        "Health": "#6fb07a",
        "Evolution": "#d96fb4",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QWidget { background:#0a0a18; }"
            "QLabel { color:#bbb; }"
            "QLineEdit { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
            "QTableWidget { background:#101023; color:#ddd; border:1px solid #26264a; }"
            "QHeaderView::section { background:#151532; color:#7d8bb0; border:none; padding:4px; font-weight:bold; }"
            "QTextBrowser { background:#0d0d1c; color:#ddd; border:1px solid #26264a; border-radius:6px; padding:10px; }"
            "QFrame#furnitureStatCard { background:#111124; border:1px solid #26264a; border-radius:8px; }"
            "QLabel#furnitureStatTitle { color:#9ca6c7; font-size:10px; font-weight:bold; }"
            "QLabel#furnitureStatValue { color:#f3f3ff; font-size:18px; font-weight:bold; }"
        )
        self._cats: list[Cat] = []
        self._furniture: list[FurnitureItem] = []
        self._furniture_by_room: dict[str, list[FurnitureItem]] = {}
        self._furniture_data: dict[str, FurnitureDefinition] = {}
        self._room_summaries: list[FurnitureRoomSummary] = []
        self._available_rooms: list[str] = list(self._ROOM_ORDER.keys())
        self._house_raw = {key: 0.0 for key in FURNITURE_ROOM_STAT_KEYS}
        self._house_effective = {key: 0.0 for key in FURNITURE_ROOM_STAT_KEYS}
        self._session_state: dict = _load_ui_state("furniture_state")
        self._restoring_session_state = False
        self._layout_splitter_restore_pending = False
        self._pending_layout_splitter_sizes: Optional[list[int]] = None
        self._splitter_restore_pending = False
        self._pending_splitter_sizes: Optional[list[int]] = None
        self._selected_room_key = ""
        self._suppress_selection_changed = False
        self._pinned_item_keys: set[int] = set()
        self._pinned_only = False
        self._table_sort_column: Optional[int] = None
        self._table_sort_order = Qt.AscendingOrder
        self._item_table_sort_column: Optional[int] = None
        self._item_table_sort_order = Qt.AscendingOrder
        self._layout_splitter: Optional[QSplitter] = None
        self._splitter: Optional[QSplitter] = None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        self._title = QLabel()
        self._title.setStyleSheet("color:#ddd; font-size:18px; font-weight:bold;")
        self._subtitle = QLabel()
        self._subtitle.setStyleSheet("color:#666; font-size:11px;")
        self._subtitle.setWordWrap(True)
        self._subtitle.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self._title)
        header.addStretch()
        header.addWidget(self._subtitle, 1)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(8)
        self._card_title_labels: dict[str, QLabel] = {}
        self._card_value_labels: dict[str, QLabel] = {}
        self._card_note_labels: dict[str, QLabel] = {}
        for stat in FURNITURE_ROOM_STAT_KEYS:
            accent = self._STAT_ACCENTS[stat]
            card = QFrame()
            card.setObjectName("furnitureStatCard")
            card.setStyleSheet(f"QFrame#furnitureStatCard {{ border-color:{accent}; }}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(2)

            title = QLabel()
            title.setObjectName("furnitureStatTitle")
            title.setStyleSheet(f"QLabel#furnitureStatTitle {{ color:{accent}; }}")
            value = QLabel("0")
            value.setObjectName("furnitureStatValue")
            note = QLabel("")
            note.setStyleSheet("color:#8d8da8; font-size:10px;")
            note.setWordWrap(True)

            card_layout.addWidget(title)
            card_layout.addWidget(value)
            card_layout.addWidget(note)
            cards.addWidget(card, 1)

            self._card_title_labels[stat] = title
            self._card_value_labels[stat] = value
            self._card_note_labels[stat] = note
        root.addLayout(cards)

        self._note = QLabel(
            _tr(
                "furniture.note.comfort_penalty",
                default="Comfort includes the -1 per cat above 4 room penalty.",
            )
        )
        self._note.setStyleSheet("color:#8d8da8; font-size:11px;")
        self._note.setWordWrap(True)
        root.addWidget(self._note)

        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setStyleSheet("QSplitter::handle { background:#1e1e38; }")
        self._layout_splitter = content_splitter

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background:#1e1e38; }")

        self._table = QTableWidget(0, 11)
        self._table.setIconSize(QSize(60, 20))
        self._table.setHorizontalHeaderLabels([
            _tr("furniture.table.order", default="#"),
            _tr("furniture.table.room", default="Room"),
            _tr("furniture.table.pieces", default="Pieces"),
            _tr("furniture.table.cats", default="Cats"),
            _tr("furniture.table.appeal", default="APP"),
            _tr("furniture.table.comfort_raw", default="COMF Raw"),
            _tr("furniture.table.crowd", default="Crowd"),
            _tr("furniture.table.comfort", default="COMF"),
            _tr("furniture.table.stimulation", default="STIM"),
            _tr("furniture.table.health", default="HEA"),
            _tr("furniture.table.mutation", default="MUT"),
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setToolTip(_tr("furniture.table.tooltip", default="Room overview with furniture stat totals"))
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(True)
        hh.setSectionsMovable(True)
        hh.setSortIndicatorShown(False)
        hh.sectionClicked.connect(self._on_table_header_clicked)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)
        for col in (2, 3):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        for col in (4, 5, 6, 7, 8, 9, 10):
            hh.setSectionResizeMode(col, QHeaderView.Interactive)
        for col, width in {
            0: 32, 1: 118, 2: 52, 3: 42, 4: 60, 5: 74, 6: 54, 7: 72, 8: 72, 9: 58, 10: 66,
        }.items():
            self._table.setColumnWidth(col, width)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        self._browser.setFrameShape(QFrame.NoFrame)
        self._browser.setStyleSheet(
            "QTextBrowser { background:#0d0d1c; color:#ddd; border:1px solid #26264a; border-radius:6px; padding:10px; }"
            "QTextBrowser h2 { color:#f0f0ff; margin-top: 4px; margin-bottom: 8px; }"
            "QTextBrowser h3 { color:#c9d6ff; margin-top: 12px; margin-bottom: 4px; }"
            "QTextBrowser table { border-collapse: collapse; margin-top: 4px; margin-bottom: 8px; }"
            "QTextBrowser td { padding: 2px 8px 2px 0; vertical-align: top; }"
            "QTextBrowser ul { margin-left: 18px; }"
            "QTextBrowser li { margin-bottom: 4px; }"
            "QTextBrowser .muted { color:#8d8da8; }"
        )

        splitter.addWidget(self._table)
        splitter.addWidget(self._browser)
        # Bias the default layout toward the detail pane so more of the lower
        # window is visible before the user starts dragging the splitter.
        splitter.setSizes([300, 420])
        splitter.splitterMoved.connect(lambda *_: self._save_session_state())
        self._splitter = splitter
        right_layout.addWidget(splitter, 1)

        item_panel = QWidget()
        item_panel_layout = QVBoxLayout(item_panel)
        item_panel_layout.setContentsMargins(0, 0, 0, 0)
        item_panel_layout.setSpacing(8)

        self._item_title = QLabel()
        self._item_title.setStyleSheet("color:#ddd; font-size:18px; font-weight:bold;")
        self._item_subtitle = QLabel()
        self._item_subtitle.setStyleSheet("color:#8d8da8; font-size:11px;")
        self._item_subtitle.setWordWrap(True)
        item_panel_layout.addWidget(self._item_title)
        item_panel_layout.addWidget(self._item_subtitle)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search_label = QLabel()
        self._search_label.setStyleSheet("color:#888; font-size:11px;")
        search_row.addWidget(self._search_label)
        self._search = QLineEdit()
        self._search.setClearButtonEnabled(True)
        self._search.setPlaceholderText(
            _tr("furniture.search.placeholder", default="Search furniture items…")
        )
        self._search.setToolTip(_tr("furniture.search.tooltip", default="Filter furniture items by name"))
        self._search.setStyleSheet(
            "QLineEdit { background:#0d0d1c; color:#ccc; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:4px 8px; }"
        )
        self._search.textChanged.connect(self._refresh_current_item_table)
        self._search.textChanged.connect(lambda _: self._save_session_state())
        search_row.addWidget(self._search, 1)
        self._pin_toggle_btn = QPushButton(_tr("bulk.toggle_pin", default="Toggle Pin"))
        self._pin_toggle_btn.setMinimumWidth(92)
        self._pin_toggle_btn.setStyleSheet(
            "QPushButton { background:#2a3a2a; color:#c8dcc8; border:1px solid #4a6a4a;"
            " border-radius:4px; padding:4px 10px; font-size:11px; font-weight:bold; }"
            "QPushButton:hover { background:#3a4a3a; }"
            "QPushButton:pressed { background:#1e2e1e; }"
        )
        self._pin_toggle_btn.clicked.connect(self._toggle_selected_item_pins)
        search_row.addWidget(self._pin_toggle_btn)
        self._pin_only_check = QToolButton()
        self._pin_only_check.setCheckable(True)
        self._pin_only_check.setCursor(Qt.PointingHandCursor)
        self._pin_only_check.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._pin_only_check.setIconSize(QSize(16, 16))
        self._pin_only_check.setFixedSize(28, 24)
        self._pin_only_check.setStyleSheet(
            "QToolButton { background:#1a1a32; color:#888; border:1px solid #2a2a4a;"
            " border-radius:4px; padding:2px; }"
            "QToolButton:hover { background:#222244; }"
            "QToolButton:checked { background:#2a2a5a; border-color:#4a4a8a; }"
        )
        self._pin_only_check.toggled.connect(self._on_pin_only_changed)
        self._pin_only_check.toggled.connect(lambda _: self._save_session_state())
        self._pin_only_check.setIcon(_make_pin_icon(True, 16))
        search_row.addWidget(self._pin_only_check)
        item_panel_layout.addLayout(search_row)

        self._item_table = QTableWidget(0, 9)
        self._item_table.setIconSize(QSize(60, 20))
        self._item_table.setHorizontalHeaderLabels([
            _tr("furniture.item.table.id", default="#"),
            _tr("furniture.item.table.pin", default="Pin"),
            _tr("furniture.item.table.item", default="Item"),
            _tr("furniture.item.table.appeal", default="APP"),
            _tr("furniture.item.table.comfort", default="COMF"),
            _tr("furniture.item.table.stim", default="STIM"),
            _tr("furniture.item.table.health", default="HEA"),
            _tr("furniture.item.table.mutation", default="MUT"),
            _tr("furniture.item.table.notes", default="Notes"),
        ])
        self._item_table.verticalHeader().setVisible(False)
        self._item_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._item_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._item_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._item_table.setSortingEnabled(False)
        self._item_table.setToolTip(_tr("furniture.item_table.tooltip", default="Furniture items in the selected room"))
        self._item_table.setAlternatingRowColors(True)
        self._item_table.setWordWrap(True)
        self._item_table.setStyleSheet(
            "QTableWidget { background:#0d0d1c; color:#ddd; border:1px solid #26264a; border-radius:6px; }"
            "QHeaderView::section { background:#151532; color:#7d8bb0; border:none; padding:4px; font-weight:bold; }"
        )
        item_header = self._item_table.horizontalHeader()
        item_header.setSectionsMovable(False)
        item_header.setSortIndicatorShown(False)
        item_header.sectionClicked.connect(self._on_item_table_header_clicked)
        item_header.setStretchLastSection(False)
        for col in range(9):
            item_header.setSectionResizeMode(col, QHeaderView.Interactive)
        self._item_table.itemClicked.connect(self._on_item_table_item_clicked)
        self._item_table.setColumnWidth(0, 32)
        self._item_table.setColumnWidth(1, 34)
        self._item_table.setColumnWidth(2, 140)
        self._item_table.setColumnWidth(3, 46)
        self._item_table.setColumnWidth(4, 46)
        self._item_table.setColumnWidth(5, 46)
        self._item_table.setColumnWidth(6, 46)
        self._item_table.setColumnWidth(7, 46)
        self._item_table.setColumnWidth(8, 124)
        item_panel_layout.addWidget(self._item_table, 1)

        content_splitter.addWidget(item_panel)
        content_splitter.addWidget(right_panel)
        # Keep the default split closer to center so the item list and details
        # share the view more evenly on first open.
        content_splitter.setSizes([640, 700])
        content_splitter.splitterMoved.connect(lambda *_: self._save_session_state())
        root.addWidget(content_splitter, 1)

        _enforce_min_font_in_widget_tree(self)
        self.retranslate_ui()
        self._browser.setHtml(self._build_empty_html())
        self._clear_item_table()

    def set_context(self, cats: list[Cat], furniture: list[FurnitureItem], furniture_data: dict[str, FurnitureDefinition] | None = None, available_rooms: list[str] | None = None):
        self._cats = cats or []
        self._furniture = furniture or []
        self._furniture_data = furniture_data or {}
        self._furniture_by_room = {}
        for item in self._furniture:
            self._furniture_by_room.setdefault(item.room or "", []).append(item)
        if available_rooms:
            allowed = {room for room in self._ROOM_ORDER.keys() if room in set(available_rooms)}
            self._available_rooms = [room for room in self._ROOM_ORDER.keys() if room in allowed]
        else:
            self._available_rooms = list(self._ROOM_ORDER.keys())
        self._build_room_summaries()
        self._refresh_table()
        self._restore_session_state()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_layout_splitter_restore()
        self._schedule_splitter_restore()

    def hideEvent(self, event):
        self._save_session_state()
        super().hideEvent(event)

    def retranslate_ui(self):
        self._title.setText(_tr("furniture.title", default="Furniture"))
        self._search_label.setText(_tr("furniture.search.label", default="Search:"))
        self._search.setPlaceholderText(_tr("furniture.search.placeholder", default="Search furniture items…"))
        self._pin_toggle_btn.setText(_tr("bulk.toggle_pin", default="Toggle Pin"))
        self._pin_toggle_btn.setToolTip(_tr("bulk.toggle_pin.tooltip", default="Toggle pin for selected furniture items"))
        self._pin_only_check.setToolTip(_tr("furniture.pin_only.tooltip", default="Show only pinned items in the current room."))
        self._pin_only_check.setIcon(_make_pin_icon(True, 16))
        self._table.setHorizontalHeaderLabels([
            _tr("furniture.table.order", default="#"),
            _tr("furniture.table.room", default="Room"),
            _tr("furniture.table.pieces", default="Pieces"),
            _tr("furniture.table.cats", default="Cats"),
            _tr("furniture.table.appeal", default="APP"),
            _tr("furniture.table.comfort_raw", default="COMF Raw"),
            _tr("furniture.table.crowd", default="Crowd"),
            _tr("furniture.table.comfort", default="COMF"),
            _tr("furniture.table.stimulation", default="STIM"),
            _tr("furniture.table.health", default="HEA"),
            _tr("furniture.table.mutation", default="MUT"),
        ])
        for stat in FURNITURE_ROOM_STAT_KEYS:
            self._card_title_labels[stat].setText(
                _tr(f"furniture.stat.{stat.lower()}", default=FURNITURE_ROOM_STAT_LABELS[stat])
            )
        self._refresh_cards()
        self._refresh_table()

    def save_session_state(self):
        self._save_session_state()

    def _save_session_state(self):
        if self._restoring_session_state:
            return
        layout_splitter_sizes = list(self._layout_splitter.sizes()) if self._layout_splitter is not None else []
        splitter_sizes = list(self._splitter.sizes()) if self._splitter is not None else []
        item_header_state = ""
        if self._item_table is not None:
            try:
                item_header_state = self._item_table.horizontalHeader().saveState().toBase64().data().decode("ascii")
            except Exception:
                item_header_state = ""
        _save_ui_state("furniture_state", {
            "selected_room": self._selected_room_key,
            "search": self._search.text().strip(),
            "layout_splitter_sizes": layout_splitter_sizes,
            "splitter_sizes": splitter_sizes,
            "item_header_state": item_header_state,
            "pinned_item_keys": sorted(self._pinned_item_keys),
            "pinned_only": self._pinned_only,
            "table_sort_column": self._table_sort_column,
            "table_sort_order": int(self._table_sort_order.value),
            "item_table_sort_column": self._item_table_sort_column,
            "item_table_sort_order": int(self._item_table_sort_order.value),
        })

    def _on_pin_only_changed(self, checked: bool):
        self._pinned_only = bool(checked)
        self._pin_only_check.setIcon(_make_pin_icon(True, 16))
        self._refresh_current_item_table()

    def _refresh_current_item_table(self, selected_item_keys: list[int] | None = None):
        selected = self._table.selectedRanges()
        if not selected:
            self._clear_item_table()
            return
        row = selected[0].topRow()
        item = self._table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole + 1)
        if not isinstance(data, dict):
            return
        summary = data.get("summary")
        if not isinstance(summary, FurnitureRoomSummary):
            return
        self._build_item_table(summary, selected_item_keys=selected_item_keys)

    def _capture_item_table_view_state(self) -> dict[str, int]:
        if self._item_table is None:
            return {}
        return {
            "vscroll": int(self._item_table.verticalScrollBar().value()),
            "hscroll": int(self._item_table.horizontalScrollBar().value()),
        }

    def _capture_item_table_selection_keys(self) -> list[int]:
        if self._item_table is None or self._item_table.selectionModel() is None:
            return []
        keys: list[int] = []
        for idx in self._item_table.selectionModel().selectedRows():
            item = self._item_table.item(idx.row(), 1)
            if item is None:
                continue
            key_value = item.data(Qt.UserRole + 1)
            if isinstance(key_value, int):
                keys.append(key_value)
        return keys

    def _restore_item_table_selection(self, keys: list[int]):
        if self._item_table is None or not keys:
            return
        selection_model = self._item_table.selectionModel()
        if selection_model is None:
            return
        key_set = set(keys)
        first = True
        for row in range(self._item_table.rowCount()):
            item = self._item_table.item(row, 1)
            if item is None:
                continue
            key_value = item.data(Qt.UserRole + 1)
            if not isinstance(key_value, int) or key_value not in key_set:
                continue
            flags = QItemSelectionModel.SelectionFlag.Rows
            if first:
                flags |= QItemSelectionModel.SelectionFlag.ClearAndSelect
                first = False
            else:
                flags |= QItemSelectionModel.SelectionFlag.Select
            selection_model.select(self._item_table.model().index(row, 0), flags)
        if first:
            selection_model.clearSelection()

    def _restore_item_table_view_state(self, state: dict[str, int]):
        if self._item_table is None or not state:
            return
        try:
            self._item_table.horizontalScrollBar().setValue(int(state.get("hscroll", 0)))
        except Exception:
            pass
        try:
            self._item_table.verticalScrollBar().setValue(int(state.get("vscroll", 0)))
        except Exception:
            pass

    def _toggle_item_pin(self, item_key: int):
        scroll_state = self._capture_item_table_view_state()
        if item_key in self._pinned_item_keys:
            self._pinned_item_keys.remove(item_key)
        else:
            self._pinned_item_keys.add(item_key)
        self._refresh_current_item_table()
        self._restore_item_table_view_state(scroll_state)

    def _toggle_selected_item_pins(self):
        selection = self._capture_item_table_selection_keys()
        if not selection:
            current_row = self._item_table.currentRow() if self._item_table is not None else -1
            if current_row >= 0:
                item = self._item_table.item(current_row, 1)
                if item is not None:
                    key_value = item.data(Qt.UserRole + 1)
                    if isinstance(key_value, int):
                        selection = [key_value]
        if not selection:
            return
        scroll_state = self._capture_item_table_view_state()
        for key in selection:
            if key in self._pinned_item_keys:
                self._pinned_item_keys.remove(key)
            else:
                self._pinned_item_keys.add(key)
        self._refresh_current_item_table(selected_item_keys=selection)
        self._restore_item_table_view_state(scroll_state)

    def _on_item_table_item_clicked(self, item: QTableWidgetItem):
        if item.column() != 1:
            return
        key_value = item.data(Qt.UserRole + 1)
        if isinstance(key_value, int):
            self._toggle_item_pin(key_value)

    def _apply_table_sort(self, column: int, order: Qt.SortOrder):
        self._table_sort_column = column
        self._table_sort_order = order
        header = self._table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)
        self._table.sortItems(column, order)

    def _on_table_header_clicked(self, column: int):
        order = Qt.AscendingOrder
        if self._table_sort_column == column:
            order = Qt.DescendingOrder if self._table_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        self._apply_table_sort(column, order)
        self._save_session_state()

    def _apply_item_table_sort(self, column: int, order: Qt.SortOrder):
        scroll_state = self._capture_item_table_view_state()
        self._item_table_sort_column = column
        self._item_table_sort_order = order
        header = self._item_table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)
        self._item_table.sortItems(column, order)
        self._restore_item_table_view_state(scroll_state)

    def _on_item_table_header_clicked(self, column: int):
        order = Qt.AscendingOrder
        if self._item_table_sort_column == column:
            order = Qt.DescendingOrder if self._item_table_sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        self._apply_item_table_sort(column, order)
        self._save_session_state()

    def _schedule_layout_splitter_restore(self):
        if self._layout_splitter is None or self._pending_layout_splitter_sizes is None or self._layout_splitter_restore_pending:
            return
        self._layout_splitter_restore_pending = True
        QTimer.singleShot(0, self._apply_pending_layout_splitter_sizes)

    def _apply_pending_layout_splitter_sizes(self):
        self._layout_splitter_restore_pending = False
        if self._layout_splitter is None or self._pending_layout_splitter_sizes is None:
            return
        if not self.isVisible() or self._layout_splitter.width() <= 0 or self._layout_splitter.height() <= 0:
            self._schedule_layout_splitter_restore()
            return
        self._restoring_session_state = True
        try:
            self._layout_splitter.setSizes(self._pending_layout_splitter_sizes)
        finally:
            self._restoring_session_state = False
        self._pending_layout_splitter_sizes = None
        self._save_session_state()

    def _schedule_splitter_restore(self):
        if self._splitter is None or self._pending_splitter_sizes is None or self._splitter_restore_pending:
            return
        self._splitter_restore_pending = True
        QTimer.singleShot(0, self._apply_pending_splitter_sizes)

    def _apply_pending_splitter_sizes(self):
        self._splitter_restore_pending = False
        if self._splitter is None or self._pending_splitter_sizes is None:
            return
        if not self.isVisible() or self._splitter.width() <= 0 or self._splitter.height() <= 0:
            self._schedule_splitter_restore()
            return
        self._restoring_session_state = True
        try:
            self._splitter.setSizes(self._pending_splitter_sizes)
        finally:
            self._restoring_session_state = False
        self._pending_splitter_sizes = None
        self._save_session_state()

    def _restore_session_state(self):
        state = self._session_state
        self._restoring_session_state = True
        try:
            search = str(state.get("search", "") or "")
            if search != self._search.text():
                self._search.blockSignals(True)
                self._search.setText(search)
                self._search.blockSignals(False)
            self._selected_room_key = str(state.get("selected_room", "") or "")
            layout_splitter_sizes = state.get("layout_splitter_sizes", [])
            if isinstance(layout_splitter_sizes, list) and len(layout_splitter_sizes) == 2:
                self._pending_layout_splitter_sizes = [
                    max(10, int(layout_splitter_sizes[0] or 0)),
                    max(10, int(layout_splitter_sizes[1] or 0)),
                ]
                self._schedule_layout_splitter_restore()
            splitter_sizes = state.get("splitter_sizes", [])
            if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2:
                self._pending_splitter_sizes = [
                    max(10, int(splitter_sizes[0] or 0)),
                    max(10, int(splitter_sizes[1] or 0)),
                ]
                self._schedule_splitter_restore()
            pinned_item_keys = state.get("pinned_item_keys", [])
            if isinstance(pinned_item_keys, list):
                pinned_keys: set[int] = set()
                for key in pinned_item_keys:
                    try:
                        pinned_keys.add(int(key))
                    except (TypeError, ValueError):
                        continue
                self._pinned_item_keys = pinned_keys
            self._pinned_only = bool(state.get("pinned_only", False))
            if hasattr(self, "_pin_only_check"):
                self._pin_only_check.blockSignals(True)
                self._pin_only_check.setChecked(self._pinned_only)
                self._pin_only_check.blockSignals(False)
                self._pin_only_check.setIcon(_make_pin_icon(True, 16))
            table_sort_column = state.get("table_sort_column")
            if isinstance(table_sort_column, int):
                self._table_sort_column = table_sort_column
                self._table_sort_order = Qt.SortOrder(int(state.get("table_sort_order", int(Qt.AscendingOrder.value))))
            item_table_sort_column = state.get("item_table_sort_column")
            if isinstance(item_table_sort_column, int):
                self._item_table_sort_column = item_table_sort_column
                self._item_table_sort_order = Qt.SortOrder(int(state.get("item_table_sort_order", int(Qt.AscendingOrder.value))))
        finally:
            self._restoring_session_state = False
        item_header_state = state.get("item_header_state", "")
        if isinstance(item_header_state, str) and item_header_state:
            try:
                self._item_table.horizontalHeader().restoreState(QByteArray.fromBase64(item_header_state.encode("ascii")))
            except Exception:
                pass
        self._refresh_current_item_table()

    def reset_to_defaults(self):
        """Restore the furniture view to its default search and splitter state."""
        self._session_state = {}
        self._restoring_session_state = True
        try:
            self._pending_layout_splitter_sizes = None
            self._pending_splitter_sizes = None
            self._search.setText("")
            self._pinned_only = False
            if hasattr(self, "_pin_only_check"):
                self._pin_only_check.blockSignals(True)
                self._pin_only_check.setChecked(False)
                self._pin_only_check.blockSignals(False)
                self._pin_only_check.setIcon(_make_pin_icon(True, 16))
            self._selected_room_key = ""
            if self._layout_splitter is not None:
                self._layout_splitter.setSizes([640, 700])
            if self._splitter is not None:
                self._splitter.setSizes([420, 300])
        finally:
            self._restoring_session_state = False
        self.retranslate_ui()
        self._refresh_table()
        self._save_session_state()

    @staticmethod
    def _fmt(value: float) -> str:
        number = float(value)
        if number == 0:
            return "0"
        if number.is_integer():
            return f"{int(number):+d}"
        return f"{number:+.1f}".rstrip("0").rstrip(".")

    @staticmethod
    def _stat_brush(value: float) -> QBrush:
        if value > 0:
            return QBrush(QColor(98, 194, 135))
        if value < 0:
            return QBrush(QColor(216, 120, 120))
        return QBrush(QColor(160, 160, 175))

    def _room_sort_key(self, room: str):
        if room == self._WHOLE_HOME_KEY:
            return (0, "")
        if room in self._ROOM_ORDER:
            return (self._ROOM_ORDER[room] + 1, room)
        if not room:
            return (7, "")
        return (50, room.lower())

    def _room_label(self, room: str) -> str:
        if room == self._WHOLE_HOME_KEY:
            return _tr("furniture.room.whole_home", default="Whole Home")
        if not room:
            return _tr("furniture.room.unplaced", default="Unplaced")
        return ROOM_DISPLAY.get(room, room)

    def _room_order_number(self, room: str) -> int:
        if room == self._WHOLE_HOME_KEY:
            return 1
        if not room:
            return 7
        order = self._ROOM_ORDER.get(room)
        if order is None:
            return 50
        return order + 2

    def _room_note(self, summary: FurnitureRoomSummary) -> str:
        if summary.room == self._WHOLE_HOME_KEY:
            return _tr(
                "furniture.detail.whole_home_note",
                default="Aggregated from all placed rooms. Unplaced items are excluded.",
            )
        if not summary.room:
            return _tr(
                "furniture.detail.unplaced_note",
                default="Unplaced items do not contribute to room stats until they are assigned to a room.",
            )
        return _tr(
            "furniture.detail.room_note",
            default="Comfort is reduced by one for every cat above four in the room.",
        )

    def _clear_item_table(self):
        self._item_title.setText(_tr("furniture.items.title", default="Furniture Items"))
        self._item_subtitle.setText(_tr("furniture.items.empty", default="Select a room to inspect the actual furniture items in that room."))
        self._item_table.setRowCount(0)

    def _item_notes(self, effects: dict[str, float]) -> str:
        notes: list[str] = []
        for key, value in sorted(effects.items(), key=lambda kv: kv[0].lower()):
            if key in FURNITURE_ROOM_STAT_KEYS or not value:
                continue
            note_value = "" if key.lower().startswith("special") and float(value) == 1.0 else f" {self._fmt(value)}"
            notes.append(f"{key}{note_value}")
        return ", ".join(notes)

    def _build_room_summaries(self):
        allowed_rooms = set(self._available_rooms or self._ROOM_ORDER.keys())
        furniture_by_room = {
            room: items
            for room, items in self._furniture_by_room.items()
            if not room or room in allowed_rooms
        }
        summaries = build_furniture_room_summaries(
            furniture_by_room,
            self._furniture_data,
            self._cats,
            room_order=self._available_rooms or self._ROOM_ORDER.keys(),
        )
        summaries.sort(key=lambda s: self._room_sort_key(s.room))
        placed_summaries = [summary for summary in summaries if summary.room]
        whole_home_items = [item for summary in placed_summaries for item in summary.items]
        whole_home_raw = {key: 0.0 for key in FURNITURE_ROOM_STAT_KEYS}
        whole_home_effective = {key: 0.0 for key in FURNITURE_ROOM_STAT_KEYS}
        whole_home_all: dict[str, float] = {}
        whole_home_cat_count = 0
        whole_home_crowd_penalty = 0
        whole_home_dead_bodies = 0
        for summary in placed_summaries:
            whole_home_cat_count += summary.cat_count
            whole_home_crowd_penalty += summary.crowd_penalty
            whole_home_dead_bodies += summary.dead_body_penalty
            for key in FURNITURE_ROOM_STAT_KEYS:
                whole_home_raw[key] += summary.raw_effects.get(key, 0.0)
                whole_home_effective[key] += summary.effective_effects.get(key, 0.0)
            for key, value in summary.all_effects.items():
                whole_home_all[key] = whole_home_all.get(key, 0.0) + value

        whole_home_summary = FurnitureRoomSummary(
            room=self._WHOLE_HOME_KEY,
            cat_count=whole_home_cat_count,
            furniture_count=len(whole_home_items),
            items=tuple(whole_home_items),
            raw_effects=whole_home_raw,
            effective_effects=whole_home_effective,
            all_effects=whole_home_all,
            crowd_penalty=whole_home_crowd_penalty,
            dead_body_penalty=whole_home_dead_bodies,
        )
        placed_summaries = [summary for summary in summaries if summary.room]
        unplaced_summaries = [summary for summary in summaries if not summary.room]
        self._room_summaries = [whole_home_summary, *placed_summaries, *unplaced_summaries]

        for key in FURNITURE_ROOM_STAT_KEYS:
            self._house_raw[key] = 0.0
            self._house_effective[key] = 0.0
        for summary in summaries:
            if not summary.room:
                continue
            for key in FURNITURE_ROOM_STAT_KEYS:
                self._house_raw[key] += summary.raw_effects.get(key, 0.0)
                self._house_effective[key] += summary.effective_effects.get(key, 0.0)

    def _refresh_cards(self):
        values = {
            "Appeal": self._house_raw.get("Appeal", 0.0),
            "Comfort": self._house_effective.get("Comfort", 0.0),
            "Stimulation": self._house_raw.get("Stimulation", 0.0),
            "Health": self._house_effective.get("Health", 0.0),
            "Evolution": self._house_raw.get("Evolution", 0.0),
        }
        notes = {
            "Appeal": _tr("furniture.card.appeal_note", default="House-wide furniture appeal."),
            "Comfort": _tr("furniture.card.comfort_note", default="After room crowding penalties."),
            "Stimulation": _tr("furniture.card.stimulation_note", default="Affects inherited item quality."),
            "Health": _tr("furniture.card.health_note", default="After dead-body penalties."),
            "Evolution": _tr("furniture.card.mutation_note", default="Mutation chance total."),
        }
        for stat in FURNITURE_ROOM_STAT_KEYS:
            self._card_value_labels[stat].setText(self._fmt(values.get(stat, 0.0)))
            self._card_note_labels[stat].setText(notes[stat])

    def _refresh_table(self):
        self._refresh_cards()
        self._table.setSortingEnabled(False)
        visible = list(self._room_summaries)

        self._table.setRowCount(len(visible))
        for row, summary in enumerate(visible):
            room_number = self._room_order_number(summary.room)
            room_label = self._room_label(summary.room)
            row_items = [
                _SortByUserRoleItem(str(room_number)),
                _SortByUserRoleItem(room_label),
                _SortByUserRoleItem(str(summary.furniture_count)),
                _SortByUserRoleItem(str(summary.cat_count)),
                _SortByUserRoleItem(self._fmt(summary.raw_effects.get("Appeal", 0.0))),
                _SortByUserRoleItem(self._fmt(summary.raw_effects.get("Comfort", 0.0))),
                _SortByUserRoleItem(self._fmt(-summary.crowd_penalty if summary.crowd_penalty else 0.0)),
                _SortByUserRoleItem(self._fmt(summary.effective_effects.get("Comfort", 0.0))),
                _SortByUserRoleItem(self._fmt(summary.raw_effects.get("Stimulation", 0.0))),
                _SortByUserRoleItem(self._fmt(summary.effective_effects.get("Health", 0.0))),
                _SortByUserRoleItem(self._fmt(summary.raw_effects.get("Evolution", 0.0))),
            ]
            user_roles = [
                room_number,
                self._room_sort_key(summary.room),
                summary.furniture_count,
                summary.cat_count,
                summary.raw_effects.get("Appeal", 0.0),
                summary.raw_effects.get("Comfort", 0.0),
                -summary.crowd_penalty if summary.crowd_penalty else 0.0,
                summary.effective_effects.get("Comfort", 0.0),
                summary.raw_effects.get("Stimulation", 0.0),
                summary.effective_effects.get("Health", 0.0),
                summary.raw_effects.get("Evolution", 0.0),
            ]
            for col, item in enumerate(row_items):
                item.setData(Qt.UserRole, user_roles[col])
                item.setData(Qt.UserRole + 1, {
                    "room": summary.room,
                    "room_display": room_label,
                    "summary": summary,
                })
                if summary.room == self._WHOLE_HOME_KEY:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if col >= 4:
                    item.setForeground(self._stat_brush(float(user_roles[col])))
                if col == 1 and not summary.room:
                    item.setForeground(QBrush(QColor(160, 160, 175)))
                self._table.setItem(row, col, item)

        if self._table.rowCount() == 0:
            self._browser.setHtml(self._build_empty_html())
            self._clear_item_table()
        else:
            if self._table_sort_column is not None:
                self._apply_table_sort(self._table_sort_column, self._table_sort_order)
            target_room = self._selected_room_key or self._WHOLE_HOME_KEY
            selected_row = None
            selected_summary = None
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 0)
                data = item.data(Qt.UserRole + 1) if item is not None else None
                if isinstance(data, dict) and data.get("room") == target_room:
                    selected_row = row
                    summary = data.get("summary")
                    if isinstance(summary, FurnitureRoomSummary):
                        selected_summary = summary
                    break
            if selected_row is None:
                selected_row = 0
                item = self._table.item(selected_row, 0)
                data = item.data(Qt.UserRole + 1) if item is not None else None
                if isinstance(data, dict):
                    summary = data.get("summary")
                    if isinstance(summary, FurnitureRoomSummary):
                        selected_summary = summary
            self._suppress_selection_changed = True
            try:
                self._table.selectRow(selected_row)
            finally:
                self._suppress_selection_changed = False
            if isinstance(selected_summary, FurnitureRoomSummary):
                self._selected_room_key = selected_summary.room
                self._browser.setHtml(self._build_room_html(selected_summary))
                self._build_item_table(selected_summary)

        self._subtitle.setText(
            _tr(
                "furniture.subtitle",
                default="{rooms} rooms | {items} pieces | {unplaced} unplaced",
                rooms=len([room for room in self._available_rooms if room]),
                items=len(self._furniture),
                unplaced=len(self._furniture_by_room.get("", [])),
            )
        )

    def _on_selection_changed(self):
        if self._suppress_selection_changed:
            return
        selected = self._table.selectedRanges()
        if not selected:
            self._selected_room_key = ""
            self._browser.setHtml(self._build_empty_html())
            self._clear_item_table()
            self._save_session_state()
            return

        row = selected[0].topRow()
        item = self._table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole + 1)
        if not isinstance(data, dict):
            return
        summary = data.get("summary")
        if not isinstance(summary, FurnitureRoomSummary):
            return
        self._selected_room_key = str(data.get("room", "") or "")
        self._browser.setHtml(self._build_room_html(summary))
        self._build_item_table(summary)
        self._save_session_state()

    def _build_empty_html(self) -> str:
        return """
        <html>
          <body style="font-family:Segoe UI, Arial, sans-serif; line-height:1.45;">
            <h2>Furniture</h2>
            <p class="muted">Load a save with furniture to inspect room stats.</p>
          </body>
        </html>
        """

    def _effect_spans(self, effects: dict[str, float]) -> str:
        if not effects:
            return '<span class="muted">No stat effects</span>'
        parts: list[str] = []
        for key in FURNITURE_ROOM_STAT_KEYS:
            value = effects.get(key, 0.0)
            if not value:
                continue
            label = FURNITURE_ROOM_STAT_LABELS[key]
            parts.append(
                f'<span style="color:{self._STAT_ACCENTS[key]}; font-weight:bold;">'
                f'{html.escape(label)} {self._fmt(value)}</span>'
            )
        for key, value in sorted(effects.items(), key=lambda kv: kv[0].lower()):
            if key in FURNITURE_ROOM_STAT_KEYS or not value:
                continue
            parts.append(
                f'<span style="color:#a8a8bd;">{html.escape(key)} {self._fmt(value)}</span>'
            )
        return ", ".join(parts)

    def _build_item_table(self, summary: FurnitureRoomSummary, selected_item_keys: list[int] | None = None):
        scroll_state = self._capture_item_table_view_state()
        selected_keys = list(selected_item_keys) if selected_item_keys is not None else self._capture_item_table_selection_keys()
        title = self._room_label(summary.room)
        subtitle = self._room_note(summary)
        self._item_title.setText(title)
        self._item_subtitle.setText(
            f"{subtitle}  Items: {summary.furniture_count}  Cats: {summary.cat_count}"
        )

        items = sorted(
            summary.items,
            key=lambda item: (
                self._room_label(item.room or "").lower(),
                self._furniture_data.get(item.item_name).display_name.lower()
                if self._furniture_data.get(item.item_name)
                else item.item_name.lower(),
                int(item.key),
            ),
        )

        query = self._search.text().strip().lower()
        if query:
            filtered_items = []
            for item in items:
                definition = self._furniture_data.get(item.item_name)
                haystack = " ".join([
                    str(item.key).lower(),
                    item.item_name.lower(),
                    self._room_label(item.room or "").lower(),
                    (definition.display_name.lower() if definition is not None else ""),
                    (definition.description.lower() if definition is not None and definition.description else ""),
                    (self._item_notes(definition.effects).lower() if definition is not None and definition.effects else ""),
                ])
                if query in haystack:
                    filtered_items.append(item)
            items = filtered_items

        if self._pinned_only:
            items = [item for item in items if int(item.key) in self._pinned_item_keys]

        self._item_table.setSortingEnabled(False)
        self._item_table.setRowCount(len(items))
        self._item_table.setHorizontalHeaderLabels([
            _tr("furniture.item.table.id", default="#"),
            _tr("furniture.item.table.pin", default="Pin"),
            _tr("furniture.item.table.item", default="Item"),
            _tr("furniture.item.table.appeal", default="APP"),
            _tr("furniture.item.table.comfort", default="COMF"),
            _tr("furniture.item.table.stim", default="STIM"),
            _tr("furniture.item.table.health", default="HEA"),
            _tr("furniture.item.table.mutation", default="MUT"),
            _tr("furniture.item.table.notes", default="Notes"),
        ])
        stat_keys = {
            3: "Appeal",
            4: "Comfort",
            5: "Stimulation",
            6: "Health",
            7: "Evolution",
        }

        for row, item in enumerate(items):
            definition = self._furniture_data.get(item.item_name)
            display = definition.display_name if definition is not None else item.item_name.replace("_", " ").title()
            desc = definition.description if definition is not None else ""
            effects = definition.effects if definition is not None else {}
            if item.is_rare:
                # Rare furniture has doubled stats; label it like the game does.
                display = _tr("furniture.rare_prefix", default="Rare {name}").format(name=display)
                effects = {k: v * 2.0 for k, v in effects.items()}
            pinned = int(item.key) in self._pinned_item_keys
            values = [
                (str(item.key), item.key),
                ("", 1 if pinned else 0),
                (display, display.lower()),
                self._sort_stat_cell(effects.get("Appeal", 0.0)),
                self._sort_stat_cell(effects.get("Comfort", 0.0)),
                self._sort_stat_cell(effects.get("Stimulation", 0.0)),
                self._sort_stat_cell(effects.get("Health", 0.0)),
                self._sort_stat_cell(effects.get("Evolution", 0.0)),
                (self._item_notes(effects) or "—", self._item_notes(effects).lower() if self._item_notes(effects) else ""),
            ]
            for col, (value, sort_key) in enumerate(values):
                cell = _SortByUserRoleItem(value)
                cell.setData(Qt.UserRole, sort_key)
                if col == 1:
                    cell.setData(Qt.UserRole + 1, int(item.key))
                    cell.setTextAlignment(Qt.AlignCenter)
                    cell.setIcon(_make_pin_icon(pinned, 16))
                    if pinned:
                        cell.setForeground(QBrush(QColor(216, 182, 106)))
                if col == 0:
                    cell.setTextAlignment(Qt.AlignCenter)
                if col in stat_keys and value not in ("—", ""):
                    cell.setForeground(self._stat_brush(float(effects.get(stat_keys[col], 0.0))))
                cell.setToolTip("\n".join(part for part in [display, desc, item.item_name, self._room_label(item.room or "")] if part))
                self._item_table.setItem(row, col, cell)

        if self._item_table_sort_column is not None:
            self._apply_item_table_sort(self._item_table_sort_column, self._item_table_sort_order)
        else:
            self._restore_item_table_view_state(scroll_state)
        self._restore_item_table_selection(selected_keys)

    @staticmethod
    def _sort_stat_cell(value: float) -> tuple[str, tuple[int, float]]:
        number = float(value or 0.0)
        if number == 0.0:
            return ("—", (1, 0.0))
        return (FurnitureView._fmt(number), (0, -number))

    def _build_room_html(self, summary: FurnitureRoomSummary) -> str:
        title = self._room_label(summary.room)
        note = self._room_note(summary)

        rows = []
        for key in FURNITURE_ROOM_STAT_KEYS:
            raw = summary.raw_effects.get(key, 0.0)
            effective = summary.effective_effects.get(key, 0.0)
            current = effective if key in ("Comfort", "Health") else raw
            rows.append(
                "<tr>"
                f"<td style='color:{self._STAT_ACCENTS[key]}; font-weight:bold;'>{html.escape(FURNITURE_ROOM_STAT_LABELS[key])}</td>"
                f"<td>{html.escape(self._fmt(raw))}</td>"
                f"<td>{html.escape(self._fmt(current))}</td>"
                "</tr>"
            )

        stats_html = "".join(rows)

        return f"""
        <html>
          <body style="font-family:Segoe UI, Arial, sans-serif; line-height:1.45;">
            <h2>{html.escape(title)}</h2>
            <p class="muted">{html.escape(note)}</p>
            <p>
              <strong>Cats:</strong> {summary.cat_count}
              &nbsp;&nbsp; <strong>Pieces:</strong> {summary.furniture_count}
              &nbsp;&nbsp; <strong>Crowd penalty:</strong> -{summary.crowd_penalty}
            </p>
            <table>
              <tr>
                <td></td>
                <td class="muted"><strong>Raw</strong></td>
                <td class="muted"><strong>Current</strong></td>
              </tr>
              {stats_html}
            </table>
            <p class="muted">The actual item list is shown in the left pane.</p>
          </body>
        </html>
        """
