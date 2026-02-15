import sys
import os
import asyncio
import traceback

sys.path.append(os.getcwd())

try:
    from src.config.config import ConfigManager
    print("Imported ConfigManager")
except ImportError:
    print("Failed to import ConfigManager")
    traceback.print_exc()

try:
    from src.network.proxy_checker import ProxyChecker
    print("Imported ProxyChecker")
except ImportError:
    print("Failed to import ProxyChecker")
    traceback.print_exc()

try:
    from src.core.account_checker import AccountValidator
    print("Imported AccountValidator")
except ImportError:
    print("Failed to import AccountValidator")
    traceback.print_exc()

async def test_proxies():
    print("\n--- Testing Proxy Checker ---")
    try:
        cm = ConfigManager()
        config = cm.load_config()
        print(f"Config loaded. Proxies enabled: {config.proxy.enabled}")
        
        checker = ProxyChecker(config)
        print("Initialized ProxyChecker")
        
        results = await checker.check_all(max_concurrent=5)
        print(f"Checked {len(results)} proxies")
        print(results[0] if results else "No results")
    except Exception as e:
        print(f"Error in test_proxies: {e}")
        traceback.print_exc()

async def test_accounts():
    print("\n--- Testing Account Validator ---")
    try:
        cm = ConfigManager()
        config = cm.load_config()
        
        validator = AccountValidator(config)
        print("Initialized AccountValidator")
        
        results = await validator.check_all()
        print(f"Checked {len(results)} accounts")
        print(results[0] if results else "No results")
    except Exception as e:
        print(f"Error in test_accounts: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_proxies())
    asyncio.run(test_accounts())
