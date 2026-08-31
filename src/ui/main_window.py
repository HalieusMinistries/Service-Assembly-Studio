from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.models.project import PROJECT_EXTENSION, Project
from src.models.timeline_item import ItemType, TimelineItem
from src.services.export_service import ExportService
from src.services.ffmpeg_locator import FFmpegLocator
from src.services.media_probe import MediaProbe
from src.ui.export_worker import ExportWorker
from src.ui.trim_dialog import TrimDialog, _format_time


class TimelineListWidget(QListWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAlternatingRowColors(True)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Service Assembly Studio")
        self.resize(1180, 760)

        try:
            self._ffmpeg = FFmpegLocator.find()
        except FileNotFoundError as exc:
            QMessageBox.critical(None, "FFmpeg Required", str(exc))
            sys.exit(1)

        self._probe = MediaProbe(self._ffmpeg)
        self._export_service = ExportService(self._ffmpeg)
        self._project = Project()
        self._export_worker: ExportWorker | None = None
        self._dirty = False

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._connect_preview()
        self._refresh_list()
        self._update_controls()

        self.setAcceptDrops(True)
        self.statusBar().showMessage("Import recordings to begin.")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        self._list = TimelineListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.model().rowsMoved.connect(lambda *args: self._on_list_reordered())

        list_box = QGroupBox("Service Sequence")
        list_layout = QVBoxLayout(list_box)
        list_layout.addWidget(QLabel("Drag items to reorder. Your order is preserved exactly on export."))
        list_layout.addWidget(self._list)

        move_row = QHBoxLayout()
        self._move_up_btn = QPushButton("Move Up")
        self._move_down_btn = QPushButton("Move Down")
        self._remove_btn = QPushButton("Remove")
        self._move_up_btn.clicked.connect(self._move_up)
        self._move_down_btn.clicked.connect(self._move_down)
        self._remove_btn.clicked.connect(self._remove_selected)
        move_row.addWidget(self._move_up_btn)
        move_row.addWidget(self._move_down_btn)
        move_row.addWidget(self._remove_btn)
        list_layout.addLayout(move_row)

        details_box = QGroupBox("Selected Section")
        details_layout = QFormLayout(details_box)

        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(self._apply_name_change)
        details_layout.addRow("Name", self._name_edit)

        self._type_combo = QComboBox()
        self._type_combo.addItem("Service Recording (speech)", ItemType.SPEECH.value)
        self._type_combo.addItem("Worship Video (music)", ItemType.WORSHIP.value)
        self._type_combo.currentIndexChanged.connect(self._apply_type_change)
        details_layout.addRow("Type", self._type_combo)

        self._duration_label = QLabel("—")
        details_layout.addRow("Duration", self._duration_label)

        self._trim_btn = QPushButton("Trim…")
        self._trim_btn.clicked.connect(self._open_trim_dialog)
        details_layout.addRow("", self._trim_btn)

        preview_box = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_box)
        self._video = QVideoWidget()
        preview_layout.addWidget(self._video, stretch=1)
        preview_controls = QHBoxLayout()
        self._preview_btn = QPushButton("Play / Pause")
        self._preview_btn.clicked.connect(self._toggle_preview)
        preview_controls.addWidget(self._preview_btn)
        preview_layout.addLayout(preview_controls)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(details_box)
        right_splitter.addWidget(preview_box)
        right_splitter.setStretchFactor(0, 0)
        right_splitter.setStretchFactor(1, 1)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(list_box)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)

        export_box = QGroupBox("Export Completed Service")
        export_layout = QVBoxLayout(export_box)
        export_path_row = QHBoxLayout()
        self._export_path_edit = QLineEdit()
        self._export_path_edit.setPlaceholderText("Choose where to save the finished MP4…")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._choose_export_path)
        export_path_row.addWidget(self._export_path_edit, stretch=1)
        export_path_row.addWidget(browse_btn)
        export_layout.addLayout(export_path_row)

        self._export_btn = QPushButton("Export MP4 for YouTube")
        self._export_btn.clicked.connect(self._start_export)
        export_layout.addWidget(self._export_btn)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        export_layout.addWidget(self._progress)

        self._progress_label = QLabel("")
        export_layout.addWidget(self._progress_label)

        self._cancel_export_btn = QPushButton("Cancel Export")
        self._cancel_export_btn.clicked.connect(self._cancel_export)
        self._cancel_export_btn.setVisible(False)
        export_layout.addWidget(self._cancel_export_btn)

        layout = QVBoxLayout(central)
        layout.addWidget(main_splitter, stretch=1)
        layout.addWidget(export_box)

        self.setStatusBar(QStatusBar())

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New Project", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save Project &As…", self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        import_action = QAction("&Import Videos…", self)
        import_action.setShortcut("Ctrl+I")
        import_action.triggered.connect(self._import_videos)
        file_menu.addAction(import_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        import_btn = QAction("Import", self)
        import_btn.triggered.connect(self._import_videos)
        toolbar.addAction(import_btn)

        export_btn = QAction("Export", self)
        export_btn.triggered.connect(self._start_export)
        toolbar.addAction(export_btn)

    def _connect_preview(self) -> None:
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._import_paths(paths)
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._export_worker.wait(3000)
        event.accept()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save changes to this project before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self._save_project()
        return True

    def _mark_dirty(self) -> None:
        self._dirty = True
        title = "Service Assembly Studio"
        if self._project.file_path:
            title = f"{Path(self._project.file_path).name} — {title}"
        if self._dirty:
            title = f"* {title}"
        self.setWindowTitle(title)

    def _mark_clean(self) -> None:
        self._dirty = False
        self._mark_dirty()

    def _current_item(self) -> TimelineItem | None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._project.items):
            return None
        return self._project.items[row]

    def _sync_items_from_list(self) -> None:
        ordered: list[TimelineItem] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None:
                continue
            timeline_item = item.data(Qt.UserRole)
            if isinstance(timeline_item, TimelineItem):
                ordered.append(timeline_item)
        self._project.items = ordered

    def _refresh_list(self) -> None:
        current_id = self._current_item().id if self._current_item() else None
        self._list.blockSignals(True)
        self._list.clear()
        for timeline_item in self._project.items:
            list_item = QListWidgetItem(self._item_label(timeline_item))
            list_item.setData(Qt.UserRole, timeline_item)
            self._list.addItem(list_item)
            if current_id and timeline_item.id == current_id:
                self._list.setCurrentItem(list_item)
        self._list.blockSignals(False)
        self._update_controls()

    def _item_label(self, item: TimelineItem) -> str:
        type_label = "Worship" if item.item_type == ItemType.WORSHIP else "Speech"
        duration = _format_time(item.effective_duration)
        missing = "" if item.source_exists else " [MISSING FILE]"
        return f"{item.display_name}  ({type_label}, {duration}){missing}"

    def _update_controls(self) -> None:
        has_items = len(self._project.items) > 0
        has_selection = self._current_item() is not None
        row = self._list.currentRow()

        self._move_up_btn.setEnabled(has_selection and row > 0)
        self._move_down_btn.setEnabled(has_selection and row < len(self._project.items) - 1)
        self._remove_btn.setEnabled(has_selection)
        self._trim_btn.setEnabled(has_selection)
        self._preview_btn.setEnabled(has_selection)
        self._export_btn.setEnabled(has_items and not self._export_in_progress())

        if not self._export_path_edit.text():
            self._export_path_edit.setText(ExportService.default_output_path(self._project))

        item = self._current_item()
        if item:
            self._name_edit.blockSignals(True)
            self._type_combo.blockSignals(True)
            self._name_edit.setText(item.display_name)
            index = self._type_combo.findData(item.item_type.value)
            if index >= 0:
                self._type_combo.setCurrentIndex(index)
            self._duration_label.setText(_format_time(item.effective_duration))
            self._name_edit.blockSignals(False)
            self._type_combo.blockSignals(False)
            self._player.setSource(QUrl.fromLocalFile(item.source_path))
        else:
            self._name_edit.clear()
            self._duration_label.setText("—")
            self._player.stop()

    def _export_in_progress(self) -> bool:
        return self._export_worker is not None and self._export_worker.isRunning()

    def _on_selection_changed(self, row: int) -> None:
        self._update_controls()

    def _on_list_reordered(self) -> None:
        self._sync_items_from_list()
        self._mark_dirty()

    def _import_videos(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Video Recordings",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.wmv *.m4v *.webm);;All Files (*.*)",
        )
        self._import_paths(paths)

    def _import_paths(self, paths: list[str]) -> None:
        if not paths:
            return

        added = 0
        errors: list[str] = []
        for path in paths:
            if not path:
                continue
            file_path = Path(path)
            if not file_path.is_file():
                continue
            try:
                info = self._probe.probe(str(file_path))
                if not info.has_video:
                    errors.append(f"{file_path.name}: no video track found.")
                    continue
                item = TimelineItem(
                    source_path=str(file_path.resolve()),
                    display_name=file_path.stem,
                    duration=info.duration,
                    trim_end=None,
                )
                self._project.items.append(item)
                added += 1
            except Exception as exc:
                errors.append(f"{file_path.name}: {exc}")

        if added:
            self._refresh_list()
            self._list.setCurrentRow(len(self._project.items) - 1)
            self._mark_dirty()
            self.statusBar().showMessage(f"Imported {added} video(s).")

        if errors:
            QMessageBox.warning(
                self,
                "Some Files Were Skipped",
                "\n".join(errors[:8]) + ("\n…" if len(errors) > 8 else ""),
            )

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row <= 0:
            return
        self._project.items[row - 1], self._project.items[row] = (
            self._project.items[row],
            self._project.items[row - 1],
        )
        self._refresh_list()
        self._list.setCurrentRow(row - 1)
        self._mark_dirty()

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._project.items) - 1:
            return
        self._project.items[row + 1], self._project.items[row] = (
            self._project.items[row],
            self._project.items[row + 1],
        )
        self._refresh_list()
        self._list.setCurrentRow(row + 1)
        self._mark_dirty()

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        item = self._project.items[row]
        answer = QMessageBox.question(
            self,
            "Remove Section",
            f"Remove '{item.display_name}' from this project?\n\nThe original recording will not be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        del self._project.items[row]
        self._refresh_list()
        self._mark_dirty()

    def _apply_name_change(self) -> None:
        item = self._current_item()
        if not item:
            return
        new_name = self._name_edit.text().strip()
        if not new_name or new_name == item.display_name:
            self._name_edit.setText(item.display_name)
            return
        item.display_name = new_name
        self._refresh_list()
        self._list.setCurrentRow(self._project.items.index(item))
        self._mark_dirty()

    def _apply_type_change(self) -> None:
        item = self._current_item()
        if not item:
            return
        value = self._type_combo.currentData()
        item.item_type = ItemType(value)
        self._refresh_list()
        self._list.setCurrentRow(self._project.items.index(item))
        self._mark_dirty()

    def _open_trim_dialog(self) -> None:
        item = self._current_item()
        if not item:
            return
        dialog = TrimDialog(item, self)
        if dialog.exec():
            self._refresh_list()
            self._list.setCurrentRow(self._project.items.index(item))
            self._mark_dirty()

    def _toggle_preview(self) -> None:
        item = self._current_item()
        if not item:
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            return
        start_ms = int(item.trim_start * 1000)
        self._player.setPosition(start_ms)
        self._player.play()

    def _new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._project = Project()
        self._export_path_edit.clear()
        self._refresh_list()
        self._mark_clean()
        self.statusBar().showMessage("New project.")

    def _open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            f"Service Assembly Project (*{PROJECT_EXTENSION});;All Files (*.*)",
        )
        if not path:
            return
        try:
            project = Project.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Open Project", str(exc))
            return

        missing = project.missing_sources()
        if missing:
            names = "\n".join(f"• {item.display_name}" for item in missing[:10])
            extra = f"\n…and {len(missing) - 10} more." if len(missing) > 10 else ""
            QMessageBox.warning(
                self,
                "Missing Source Files",
                "Some recordings referenced by this project could not be found:\n\n"
                f"{names}{extra}",
            )

        self._project = project
        if project.last_export_path:
            self._export_path_edit.setText(project.last_export_path)
        else:
            self._export_path_edit.setText(ExportService.default_output_path(project))
        self._refresh_list()
        self._mark_clean()
        self.statusBar().showMessage(f"Opened {Path(path).name}.")

    def _save_project(self) -> bool:
        if not self._project.file_path:
            return self._save_project_as()
        try:
            self._sync_items_from_list()
            self._project.save()
            self._mark_clean()
            self.statusBar().showMessage("Project saved.")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Save Project", str(exc))
            return False

    def _save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            self._project.file_path or f"service{PROJECT_EXTENSION}",
            f"Service Assembly Project (*{PROJECT_EXTENSION})",
        )
        if not path:
            return False
        if not path.endswith(PROJECT_EXTENSION):
            path += PROJECT_EXTENSION
        try:
            self._sync_items_from_list()
            self._project.save(path)
            self._mark_clean()
            self.statusBar().showMessage("Project saved.")
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Save Project", str(exc))
            return False

    def _choose_export_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Completed Service As",
            self._export_path_edit.text() or ExportService.default_output_path(self._project),
            "MP4 Video (*.mp4)",
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self._export_path_edit.setText(path)

    def _start_export(self) -> None:
        if self._export_in_progress():
            return

        self._sync_items_from_list()
        if not self._project.items:
            QMessageBox.information(self, "Nothing to Export", "Import and arrange sections first.")
            return

        output_path = self._export_path_edit.text().strip()
        if not output_path:
            self._choose_export_path()
            output_path = self._export_path_edit.text().strip()
        if not output_path:
            return

        if not output_path.lower().endswith(".mp4"):
            output_path += ".mp4"
            self._export_path_edit.setText(output_path)

        if Path(output_path).exists():
            answer = QMessageBox.question(
                self,
                "Replace Existing File?",
                f"{output_path}\n\nThis file already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self._project.last_export_path = output_path
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._progress_label.setText("Starting export…")
        self._cancel_export_btn.setVisible(True)
        self._export_btn.setEnabled(False)

        self._export_worker = ExportWorker(self._export_service, self._project, output_path)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished_ok.connect(self._on_export_finished)
        self._export_worker.failed.connect(self._on_export_failed)
        self._export_worker.start()

    def _cancel_export(self) -> None:
        if self._export_worker and self._export_worker.isRunning():
            self._export_worker.cancel()
            self._progress_label.setText("Cancelling…")

    def _on_export_progress(self, pct: int, message: str) -> None:
        self._progress.setValue(pct)
        self._progress_label.setText(message)

    def _on_export_finished(self, path: str) -> None:
        self._progress.setValue(100)
        self._progress_label.setText("Export complete.")
        self._cancel_export_btn.setVisible(False)
        self._export_btn.setEnabled(True)
        self._export_worker = None
        self.statusBar().showMessage(f"Exported to {path}")
        QMessageBox.information(
            self,
            "Export Complete",
            f"Your completed service was saved to:\n\n{path}",
        )

    def _on_export_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._progress_label.setText("")
        self._cancel_export_btn.setVisible(False)
        self._export_btn.setEnabled(True)
        self._export_worker = None
        if "cancelled" in message.lower():
            self.statusBar().showMessage("Export cancelled.")
            return
        QMessageBox.critical(self, "Export Failed", message)
        self.statusBar().showMessage("Export failed.")


def run_app() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Service Assembly Studio")
    app.setOrganizationName("Service Assembly Studio")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
