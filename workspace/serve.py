import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
import uvicorn
from app.main import app
uvicorn.run(app, host='127.0.0.1', port=8000, log_level='warning')
