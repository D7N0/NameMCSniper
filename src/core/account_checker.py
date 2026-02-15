import asyncio
import aiohttp
import logging
from typing import List, Dict, Any
from src.config.config import AppConfig

logger = logging.getLogger(__name__)

class AccountValidator:
    """Validates Minecraft bearer tokens"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.tokens = config.snipe.bearer_tokens
        self.api_url = "https://api.minecraftservices.com/minecraft/profile"

    async def check_token(self, token: str) -> Dict[str, Any]:
        """Validate a single token"""
        masked_token = f"...{token[-6:]}" if len(token) > 6 else "Invalid"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "MinecraftSniper/1.0"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.api_url, headers=headers, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "valid": True,
                            "name": data.get("name", "Unknown"),
                            "uuid": data.get("id", "Unknown"),
                            "token": token,
                            "masked": masked_token
                        }
                    elif response.status == 401:
                        return {
                            "valid": False,
                            "error": "Unauthorized (Expired/Invalid)",
                            "token": token,
                            "masked": masked_token
                        }
                    else:
                        return {
                            "valid": False,
                            "error": f"HTTP {response.status}",
                            "token": token,
                            "masked": masked_token
                        }
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "token": token,
                "masked": masked_token
            }

    async def check_all(self) -> List[Dict[str, Any]]:
        """Check all configured tokens"""
        if not self.tokens:
            return []
            
        tasks = [self.check_token(token) for token in self.tokens]
        results = await asyncio.gather(*tasks)
        return list(results)
