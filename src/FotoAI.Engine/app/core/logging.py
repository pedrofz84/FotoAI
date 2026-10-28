import sys
from loguru import logger
from app.config.settings import settings

def setup_logging():
    settings.init_dirs()
    log_file = settings.LOGS_DIR / "Engine_{time:YYYY-MM-DD}.log"
    
    # Substituir os logs padrão do Python pelos do Loguru
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logger.add(str(log_file), rotation="10 MB", retention="7 days", level="DEBUG")
    
    logger.info("FotoAI Engine Logging Initialized.")
