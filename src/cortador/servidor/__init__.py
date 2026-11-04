"""Paquete del servicio web de ScoutCuts.

Los submodulos se importan explicitamente para que `import cortador` siga
funcionando sin las dependencias del extra `servidor` instaladas.
"""

from __future__ import annotations

__all__ = ["almacen", "cola", "procesador", "usuarios"]
