import uvicorn
from config import settings
from web.server import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")
