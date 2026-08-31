from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.models.project import Project
from src.services.export_service import ExportService


class ExportWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, export_service: ExportService, project: Project, output_path: str) -> None:
        super().__init__()
        self._export_service = export_service
        self._project = project
        self._output_path = output_path

    def run(self) -> None:
        try:
            result = self._export_service.export_project(
                self._project,
                self._output_path,
                progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self._export_service.cancel()
