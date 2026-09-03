"""Perfil de camara: el ROI del cajon de bateo, calibrado una sola vez."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Perfil:
    """ROI en pixeles sobre el fotograma original.

    El rectangulo cubre los dos cajones (zurdo y diestro) y el plato: asi un unico
    ROI vale para todos los peloteros.
    """

    x: int
    y: int
    ancho: int
    alto: int
    video_ancho: int
    video_alto: int
    creado: str = ""
    origen: str = ""

    def __post_init__(self) -> None:
        if self.ancho <= 0 or self.alto <= 0:
            raise ValueError("El ROI debe tener ancho y alto positivos")
        if self.x < 0 or self.y < 0:
            raise ValueError("El ROI no puede empezar fuera del fotograma")
        if self.x + self.ancho > self.video_ancho or self.y + self.alto > self.video_alto:
            raise ValueError("El ROI se sale del fotograma")

    @property
    def crop(self) -> str:
        """Filtro crop de ffmpeg."""
        return f"crop={self.ancho}:{self.alto}:{self.x}:{self.y}"

    def guardar(self, ruta: str | Path) -> None:
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = asdict(self)
        datos["creado"] = self.creado or datetime.now(timezone.utc).isoformat(timespec="seconds")
        ruta.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def cargar(cls, ruta: str | Path) -> "Perfil":
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        return cls(**datos)
