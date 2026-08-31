from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.models.timeline_item import TimelineItem


def _format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


class TrimDialog(QDialog):
    def __init__(self, item: TimelineItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item
        self._duration = item.duration
        self._updating = False

        self.setWindowTitle(f"Trim — {item.display_name}")
        self.resize(720, 520)

        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._video = QVideoWidget(self)
        self._player.setVideoOutput(self._video)

        self._start_slider = QSlider(Qt.Horizontal)
        self._end_slider = QSlider(Qt.Horizontal)
        max_ms = max(int(self._duration * 1000), 1)
        self._start_slider.setRange(0, max_ms)
        self._end_slider.setRange(0, max_ms)
        self._start_slider.setValue(int(item.trim_start * 1000))
        end_value = int((item.trim_end if item.trim_end is not None else self._duration) * 1000)
        self._end_slider.setValue(end_value)

        self._start_label = QLabel()
        self._end_label = QLabel()
        self._length_label = QLabel()

        self._play_button = QPushButton("Play Selection")
        self._play_button.clicked.connect(self._toggle_playback)

        form = QFormLayout()
        form.addRow("Start", self._wrap_slider(self._start_slider, self._start_label))
        form.addRow("End", self._wrap_slider(self._end_slider, self._end_label))
        form.addRow("Selected length", self._length_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._video, stretch=1)
        layout.addLayout(form)
        layout.addWidget(self._play_button)
        layout.addWidget(buttons)

        self._start_slider.valueChanged.connect(self._on_start_changed)
        self._end_slider.valueChanged.connect(self._on_end_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        self._player.setSource(QUrl.fromLocalFile(item.source_path))
        self._update_labels()

    def _wrap_slider(self, slider: QSlider, label: QLabel) -> QWidget:
        box = QHBoxLayout()
        box.addWidget(slider, stretch=1)
        box.addWidget(label)
        wrapper = QWidget()
        wrapper.setLayout(box)
        return wrapper

    def _on_start_changed(self, value: int) -> None:
        if self._updating:
            return
        if value >= self._end_slider.value():
            self._updating = True
            self._start_slider.setValue(max(0, self._end_slider.value() - 100))
            self._updating = False
        self._update_labels()

    def _on_end_changed(self, value: int) -> None:
        if self._updating:
            return
        if value <= self._start_slider.value():
            self._updating = True
            self._end_slider.setValue(min(self._start_slider.maximum(), self._start_slider.value() + 100))
            self._updating = False
        self._update_labels()

    def _update_labels(self) -> None:
        start = self._start_slider.value() / 1000.0
        end = self._end_slider.value() / 1000.0
        self._start_label.setText(_format_time(start))
        self._end_label.setText(_format_time(end))
        self._length_label.setText(_format_time(end - start))

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self._play_button.setText("Play Selection")
            return

        start_ms = self._start_slider.value()
        self._player.setPosition(start_ms)
        self._player.play()
        self._play_button.setText("Pause")

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._player.playbackState() != QMediaPlayer.PlayingState:
            return
        if self._player.position() >= self._end_slider.value():
            self._player.pause()
            self._play_button.setText("Play Selection")

    def _accept_if_valid(self) -> None:
        start = self._start_slider.value() / 1000.0
        end = self._end_slider.value() / 1000.0
        if end <= start:
            return
        self._item.trim_start = start
        self._item.trim_end = end if end < self._duration else None
        self.accept()

    def closeEvent(self, event) -> None:
        self._player.stop()
        super().closeEvent(event)
