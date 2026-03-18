from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from settings import settings


@dataclass(frozen=True)
class PipelinePaths:
    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def data_raw(self) -> Path:
        return self.data_dir / "raw"

    @property
    def data_external(self) -> Path:
        return self.data_dir / "external"

    @property
    def data_interim(self) -> Path:
        return self.data_dir / "interim"

    @property
    def data_processed(self) -> Path:
        return self.data_dir / "processed"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def artifacts_models(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def artifacts_metrics(self) -> Path:
        return self.artifacts_dir / "metrics"

    @property
    def artifacts_reports(self) -> Path:
        return self.artifacts_dir / "reports"

    @property
    def artifacts_exports(self) -> Path:
        return self.artifacts_dir / "exports"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def runs_train(self) -> Path:
        return self.runs_dir / "train"

    @property
    def runs_eval(self) -> Path:
        return self.runs_dir / "eval"

    @property
    def runs_inference(self) -> Path:
        return self.runs_dir / "inference"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    def ensure_dirs(self) -> None:
        dirs = [
            self.root,
            self.data_raw,
            self.data_external,
            self.data_interim,
            self.data_processed,
            self.artifacts_models,
            self.artifacts_metrics,
            self.artifacts_reports,
            self.artifacts_exports,
            self.runs_train,
            self.runs_eval,
            self.runs_inference,
            self.logs_dir,
            self.tmp_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


def get_pipeline_paths() -> PipelinePaths:
    return PipelinePaths(root=settings.pipeline_root)
