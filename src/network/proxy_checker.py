import asyncio
import aiohttp
import time
import logging
from typing import List, Dict, Any, Optional
from src.config.config import AppConfig

logger = logging.getLogger(__name__)

class ProxyChecker:
    """Validates proxies by testing connectivity to a target URL"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.proxies = config.proxy.proxies
        # Use a reliable target that represents the actual use case
        self.target_url = "https://api.minecraftservices.com/status" 
        self.timeout = 10 # Seconds

    async def check_proxy(self, proxy: str) -> Dict[str, Any]:
        """Check a single proxy"""
        proxy_url = proxy
        if not proxy.startswith("http"):
            proxy_url = f"http://{proxy}"
            
        start_time = time.time()
        status = "dead"
        latency = 0
        error = None
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.target_url, 
                    proxy=proxy_url, 
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    latency = (time.time() - start_time) * 1000
                    if response.status == 200:
                        status = "alive"
                    else:
                        status = f"error_{response.status}"
                        error = f"HTTP {response.status}"
                        
        except asyncio.TimeoutError:
            status = "timeout"
            error = "Connection timed out"
        except Exception as e:
            status = "error"
            error = str(e)
            
        return {
            "proxy": proxy,
            "status": status,
            "latency_ms": round(latency, 2),
            "error": error
        }

    async def check_all(self, max_concurrent: int = 50) -> List[Dict[str, Any]]:
        """Check all configured proxies concurrently"""
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def bounded_check(proxy):
            async with semaphore:
                return await self.check_proxy(proxy)
        
        tasks = [bounded_check(proxy) for proxy in self.proxies]
        
        if not tasks:
            return []
            
        # Run with progress tracking potential here, but keeping it simple for now
        results = await asyncio.gather(*tasks)
        return list(results)
