import logging
from bot import app

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s'
    )
    logging.info("Starting Business Bot...")
    app.run()
