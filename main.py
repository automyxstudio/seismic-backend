"""
Punto de entrada de la API FastAPI.

Arrancado por uvicorn en el contenedor 'api' del docker-compose:
  uvicorn src.api.main:app --host 0.0.0.0 --port 8000

Este archivo existe para facilitar el arranque local fuera de Docker:
  python main.py
"""

import uvicorn
from src.config.settings import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "src.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_env == "development",
    )
