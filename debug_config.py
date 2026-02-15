import sys
import os
print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")
print(f"Current working directory: {os.getcwd()}")

try:
    import pydantic
    print(f"Pydantic version: {pydantic.VERSION}")
    print(f"Pydantic location: {pydantic.__file__}")
except ImportError as e:
    print(f"Failed to import pydantic: {e}")

try:
    sys.path.append(os.getcwd())
    from src.config.config import ConfigManager
    print("Successfully imported ConfigManager")
    
    cm = ConfigManager()
    print("Initialized ConfigManager")
    
    config = cm.load_config()
    print("Loaded config successfully")
    print(f"Proxies enabled: {config.proxy.enabled}")
    if config.proxy.proxies:
        print(f"Loaded {len(config.proxy.proxies)} proxies")
        
except Exception as e:
    print(f"Error during config testing: {e}")
    import traceback
    traceback.print_exc()
