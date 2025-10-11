import asyncio
import json
import logging
import os
import sys

from bot import Bot


async def run_bot(config: dict):
    """
    Initialize and run a single bot instance
    
    Args:
        config: Configuration dictionary for the bot
    """
    session_name = config.get("session_name")
    
    if not session_name:
        logging.error("Bot configuration missing 'session_name'")
        return
    
    logging.info(f"Initializing bot: {session_name}")
    
    try:
        # Create bot instance
        bot = Bot(
            session_name=session_name,
            api_id=config.get("api_id"),
            api_hash=config.get("api_hash"),
            bot_owner_id=config.get("bot_owner_id"),
            db_path=config.get("database_path", f"data/{session_name}.db"),
            gemini_api_key=config.get("gemini_api_key", "")
        )
        
        # Start the bot
        await bot.start()
        logging.info(f"Bot {session_name} started successfully.")
        
        # Keep running indefinitely
        await asyncio.Event().wait()
        
    except Exception as e:
        logging.error(f"Failed to start or run bot {session_name}: {e}", exc_info=True)


async def main():
    """Main entry point - loads config and starts all bots"""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s'
    )
    
    logging.info("Starting Business Bot Service...")
    
    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)
    
    # Load configuration
    config_path = "config.json"
    
    if not os.path.exists(config_path):
        logging.error(f"Configuration file not found: {config_path}")
        logging.error("Please create config.json based on config.json.example")
        sys.exit(1)
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            configs = json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"Could not parse config.json: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading config.json: {e}")
        sys.exit(1)
    
    if not configs:
        logging.warning("Config file is empty. No bots to run.")
        sys.exit(0)
    
    if not isinstance(configs, list):
        logging.error("config.json should contain a JSON array of bot configurations")
        sys.exit(1)
    
    logging.info(f"Loaded {len(configs)} bot configuration(s)")
    
    # Validate configurations
    for i, config in enumerate(configs):
        required_fields = ["session_name", "api_id", "api_hash", "bot_owner_id", "database_path", "gemini_api_key"]
        missing = [field for field in required_fields if field not in config]
        
        if missing:
            logging.error(f"Bot config #{i+1} is missing required fields: {missing}")
            sys.exit(1)
        
        # Warn if Gemini API key is empty
        if not config.get("gemini_api_key"):
            logging.warning(f"Bot config #{i+1} ({config.get('session_name')}) has empty gemini_api_key. AI features will not work.")
    
    # Create and run tasks for each bot
    tasks = [asyncio.create_task(run_bot(config)) for config in configs]
    
    logging.info(f"Starting {len(tasks)} bot(s)...")
    
    # Wait for all tasks
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
