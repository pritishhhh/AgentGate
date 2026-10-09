import uvicorn

from .app import create_app
from .bootstrap import initialize
from .config import Settings

settings = Settings.from_env()
initialize(settings.data_dir)
uvicorn.run(create_app(settings), host="0.0.0.0", port=8000)
