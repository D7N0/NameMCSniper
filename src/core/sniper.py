import asyncio
import aiohttp
import time
import logging
import gc
import psutil
import sys
import os
import statistics
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Set, Union
from dataclasses import dataclass

from src.notifications.discord_notifier import DiscordNotifier
from src.config.config import AppConfig
from src.core.time_sync import TimeSync, AccurateTimer
from collections import defaultdict

logger = logging.getLogger(__name__)

class RateLimitTracker:
    """Track rate limits per token to optimize request distribution"""
    
    def __init__(self):
        self.token_limits = defaultdict(lambda: {'last_limited': 0, 'backoff_until': 0})
    
    def is_token_limited(self, token: str) -> bool:
        """Check if a token is currently rate limited"""
        token_key = token[-8:] if token else "default"
        return time.time() < self.token_limits[token_key]['backoff_until']
    
    def record_rate_limit(self, token: str, retry_after: float):
        """Record a rate limit for a token"""
        token_key = token[-8:] if token else "default"
        self.token_limits[token_key]['last_limited'] = time.time()
        self.token_limits[token_key]['backoff_until'] = time.time() + retry_after
        logger.debug(f"Token ...{token_key} rate limited until {self.token_limits[token_key]['backoff_until']}")
    
    def get_best_token(self, tokens: list) -> str:
        """Get the token with the least recent rate limiting"""
        if not tokens:
            return None
        
        # Filter out currently rate limited tokens
        available_tokens = [t for t in tokens if not self.is_token_limited(t)]
        
        if not available_tokens:
            # All tokens are rate limited, return the one that recovers soonest
            return min(tokens, key=lambda t: self.token_limits[t[-8:]]['backoff_until'])
        
        # Return token with oldest rate limit (or never limited)
        return min(available_tokens, key=lambda t: self.token_limits[t[-8:]]['last_limited'])

@dataclass
class SnipeResult:
    """Result of a snipe attempt"""
    success: bool
    username: str
    attempts: int
    total_time: float
    error_message: Optional[str] = None

class UsernameSniper:
    """Simple username sniper - countdown and claim"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.discord_notifier = None
        self.session = None
        self._session_connector = None
        self.proxy_manager = None
        self.is_running = False
        
        # Initialize time synchronization
        self.time_sync = TimeSync()
        self.timer = AccurateTimer(self.time_sync)
        
        # Initialize rate limiting tracker
        self.rate_limit_tracker = RateLimitTracker()
        
        # Track sent notifications to prevent duplicates
        self.sent_notifications = set()
        
        # Connection pooling stats
        self._connection_stats = {
            'requests_made': 0,
            'connections_reused': 0,
            'connection_errors': 0
        }
        
        # Initialize proxy manager if enabled
        if self.config.proxy.enabled and self.config.proxy.proxies:
            try:
                from src.network.proxy_manager import ProxyManager
                self.proxy_manager = ProxyManager(
                    proxy_list=self.config.proxy.proxies,
                    rotation_enabled=self.config.proxy.rotation_enabled,
                    timeout=self.config.proxy.timeout
                )
                logger.info("Proxy manager initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize proxy manager: {e}")
                logger.warning("Continuing without proxy support")
                self.proxy_manager = None
        
        # Initialize Discord notifier if enabled
        if self.config.discord.enabled and self.config.discord.webhook_url:
            self.discord_notifier = DiscordNotifier(
                webhook_url=self.config.discord.webhook_url,
                mention_role_id=self.config.discord.mention_role_id,
                embed_color=self.config.discord.embed_color
            )
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure HTTP session exists with connection pooling"""
        if self.session is None or self.session.closed:
            # Create optimized TCP connector for connection pooling
            self._session_connector = aiohttp.TCPConnector(
                limit=500,  # Max total connections
                limit_per_host=100,  # Max connections per host
                ttl_dns_cache=300,  # Cache DNS for 5 minutes
                use_dns_cache=True,
                keepalive_timeout=30,  # Keep connections alive for 30s
                enable_cleanup_closed=True,
                force_close=False,  # Reuse connections
                # TCP optimizations
                ssl=False  # Minecraft API uses HTTP
            )
            
            timeout_seconds = self.config.proxy.timeout if self.proxy_manager else 5
            timeout = aiohttp.ClientTimeout(
                total=timeout_seconds,
                connect=2,  # Fast connection timeout
                sock_read=timeout_seconds
            )
            
            self.session = aiohttp.ClientSession(
                connector=self._session_connector,
                timeout=timeout,
                # Optimize headers
                headers={
                    'User-Agent': 'MinecraftSniper/2.0',
                    'Accept': 'application/json',
                    'Connection': 'keep-alive'
                }
            )
            logger.info("🔌 HTTP session created with connection pooling enabled")
        
        return self.session
    
    async def _prewarm_connections(self, num_connections: int = 5):
        """Pre-warm connections to Minecraft API"""
        logger.info(f"🔥 Pre-warming {num_connections} connections to Minecraft API...")
        session = await self._ensure_session()
        
        # Make lightweight requests to establish connections
        tasks = []
        for i in range(num_connections):
            # Use a lightweight endpoint
            task = self._prewarm_single_connection(session, i)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successful = sum(1 for r in results if not isinstance(r, Exception))
        logger.info(f"✅ Pre-warmed {successful}/{num_connections} connections")
    
    async def _prewarm_single_connection(self, session: aiohttp.ClientSession, index: int):
        """Pre-warm a single connection"""
        try:
            url = "https://api.minecraftservices.com/minecraft/profile/name/availability/check/TestPrewarm"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                await resp.read()  # Consume response to complete connection
                logger.debug(f"Pre-warmed connection {index+1}")
        except Exception as e:
            logger.debug(f"Pre-warm connection {index+1} failed: {e}")
            raise
    
    async def cleanup(self):
        """Cleanup resources properly"""
        logger.info("🧹 Cleaning up resources...")
        
        # Log connection stats
        if self._connection_stats['requests_made'] > 0:
            reuse_rate = (self._connection_stats['connections_reused'] / 
                         self._connection_stats['requests_made'] * 100)
            logger.info(f"📊 Connection reuse rate: {reuse_rate:.1f}%")
        
        # Close HTTP session
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("HTTP session closed")
        
        # Close connector
        if self._session_connector and not self._session_connector.closed:
            await self._session_connector.close()
            logger.info("TCP connector closed")
        
        # Close Discord notifier
        if self.discord_notifier:
            try:
                await self.discord_notifier.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Discord notifier: {e}")
    
    async def snipe_with_fallback(self, drop_times: List[datetime], username: str) -> SnipeResult:
        """Snipe a username with multiple fallback drop times"""
        if not drop_times:
            logger.error("No drop times provided")
            return SnipeResult(
                success=False,
                username=username,
                attempts=0,
                total_time=0,
                error_message="No drop times provided"
            )
        
        logger.info(f"Starting fallback sniper for username: {username}")
        logger.info(f"Drop times: {[dt.isoformat() for dt in drop_times]}")
        
        # Try each drop time in order
        for i, drop_time in enumerate(drop_times, 1):
            logger.info(f"🎯 Attempting drop window {i}/{len(drop_times)}: {drop_time.isoformat()}")
            
            if self.discord_notifier:
                try:
                    await self.discord_notifier.notify_status_update(
                        f"🎯 **Drop Window {i}/{len(drop_times)}**\n"
                        f"Username: **{username}**\n"
                        f"Drop time: {drop_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send fallback window notification: {e}")
            
            result = await self.snipe_at_time(drop_time, username)
            
            if result.success:
                logger.info(f"🎉 SUCCESS on drop window {i}!")
                return result
            else:
                logger.warning(f"❌ Drop window {i} failed: {result.error_message}")
                
                # If there are more drop times, wait a bit before next attempt
                if i < len(drop_times):
                    logger.info(f"⏳ Preparing for next drop window in 5 seconds...")
                    await asyncio.sleep(5)
        
        # All drop windows failed
        logger.error(f"❌ All {len(drop_times)} drop windows failed for {username}")
        return SnipeResult(
            success=False,
            username=username,
            attempts=0,
            total_time=0,
            error_message=f"All {len(drop_times)} drop windows failed"
        )

    async def snipe_at_time(self, drop_time: datetime, username: str) -> SnipeResult:
        """Snipe a username at the specified time"""
        if self.is_running:
            logger.warning("Sniper is already running")
            return SnipeResult(
                success=False,
                username=username,
                attempts=0,
                total_time=0,
                error_message="Sniper already running"
            )
        
        self.is_running = True
        # Reset notification tracking for new snipe
        self.sent_notifications.clear()
        
        logger.info(f"Starting sniper for username: {username}")
        logger.info(f"Drop time: {drop_time.isoformat()}")
        
        try:
            # Check bearer token
            if not self.config.snipe.bearer_token or self.config.snipe.bearer_token == "your_minecraft_bearer_token_here":
                logger.error("Bearer token not configured!")
                return SnipeResult(
                    success=False,
                    username=username,
                    attempts=0,
                    total_time=0,
                    error_message="Bearer token not configured"
                )
            
            
            # Ensure persistent HTTP session exists (reuses connections)
            await self._ensure_session()
            logger.info("✅ Using persistent HTTP session with connection pooling")
            
            if self.proxy_manager:
                logger.info(f"Proxy support enabled with {len(self.config.proxy.proxies)} proxies")
            else:
                logger.info("Using direct connection (no proxies configured)")
            
            # Initialize Discord session
            if self.discord_notifier:
                await self.discord_notifier.__aenter__()
            
            # Send Discord notification
            if self.discord_notifier:
                try:
                    await self.discord_notifier.notify_status_update(
                        f"🎯 Started sniper for **{username}**\n"
                        f"Drop time: {drop_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                        f"Will start sniping 0.1 seconds before drop time"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Discord notification: {e}")
            
            # Sync time first
            await self.time_sync.sync_time()
            
            # Wait until snipe time with accurate timer (start 0.4s early for competitive edge)
            snipe_start_time = drop_time - timedelta(milliseconds=400)
            
            # Application Performance Tuning
            if self.config.performance.high_priority:
                try:
                    p = psutil.Process(os.getpid())
                    # Windows specific priority classes
                    if sys.platform == "win32":
                        p.nice(psutil.HIGH_PRIORITY_CLASS)
                        logger.info("🚀 Process priority set to HIGH")
                    else:
                        p.nice(-10) # Unix nice value
                except Exception as e:
                    logger.warning(f"Failed to set process priority: {e}")

            # Connection Pre-warming
            if self.config.performance.pre_warm_connections:
                try:
                    await self._prewarm_connections(num_connections=10)
                except Exception as e:
                    logger.warning(f"Connection pre-warming failed (continuing anyway): {e}")

            # Disable Garbage Collection
            if self.config.performance.gc_disable:
                gc.disable()
                logger.info("🗑️ Garbage collection disabled for critical window")

            await self.timer.wait_until(
                snipe_start_time, 
                callback=lambda remaining, current, target: self._handle_countdown(remaining, current, target, username),
                busy_wait_ms=self.config.performance.busy_wait_ms
            )
            
            # Start sniping
            result = await self._start_sniping(username)
            
            # Send final notification
            if self.discord_notifier:
                try:
                    await self.discord_notifier.notify_snipe_result(
                        username=result.username,
                        success=result.success,
                        attempts=result.attempts,
                        response_time=0,
                        error_message=result.error_message
                    )
                except Exception as e:
                    logger.warning(f"Failed to send final Discord notification: {e}")
            
            return result
        
        except Exception as e:
            logger.error(f"Error in sniper: {e}")
            return SnipeResult(
                success=False,
                username=username,
                attempts=0,
                total_time=0,
                error_message=str(e)
            )
        finally:
            self.is_running = False
            
            # Re-enable Garbage Collection
            if self.config.performance.gc_disable:
                gc.enable()
                logger.info("🗑️ Garbage collection re-enabled")
            
            # Note: Session is kept alive for reuse across snipes
            # Call cleanup() explicitly when done with all snipes
            if self.discord_notifier:
                try:
                    await self.discord_notifier.close()
                except Exception as e:
                    logger.debug(f"Discord notifier already closed: {e}")
    
    async def _handle_countdown(self, time_remaining: float, current_time: datetime, target_time: datetime, username: str):
        """Handle countdown notifications with accurate timing"""
        # Notification intervals (in seconds) - more precise timing
        notification_intervals = [3600, 1800, 600, 300, 60, 30, 10, 5, 1]  # 1h, 30m, 10m, 5m, 1m, 30s, 10s, 5s, 1s
        
        # Check if we should send a notification
        for interval in notification_intervals:
            # Check if we're within 0.5 seconds of the notification time
            if abs(time_remaining - interval) <= 0.5 and interval not in self.sent_notifications:
                self.sent_notifications.add(interval)
                await self._send_countdown_notification(interval, target_time, username)
                break
        
        # Show console countdown for last 60 seconds
        if time_remaining <= 60:
            logger.info(f"🚨 Starting in {time_remaining:.1f} seconds... (Accurate time: {current_time.strftime('%H:%M:%S.%f')[:-3]})")
        elif time_remaining <= 600:  # Last 10 minutes
            logger.info(f"⏰ {time_remaining:.0f} seconds remaining...")
    
    async def _send_countdown_notification(self, seconds_remaining: int, drop_time: datetime, username: str):
        """Send Discord countdown notification"""
        if not self.discord_notifier:
            return
        
        # Format time remaining
        if seconds_remaining >= 3600:
            time_str = f"{seconds_remaining // 3600} hour(s)"
        elif seconds_remaining >= 60:
            time_str = f"{seconds_remaining // 60} minute(s)"
        else:
            time_str = f"{seconds_remaining} second(s)"
        
        try:
            await self.discord_notifier.notify_drop_countdown(
                username=username,
                time_remaining=time_str,
                drop_time=drop_time
            )
            logger.info(f"📢 Sent countdown notification: {time_str} remaining")
        except Exception as e:
            logger.warning(f"Failed to send countdown notification: {e}")
    
    async def _start_sniping(self, username: str) -> SnipeResult:
        """Start the sniping process with dynamic concurrency adjustment"""
        logger.info("🚨 Starting sniping process!")
        
        start_time = time.time()
        stop_time = start_time + 10.1  # Snipe for 10.1 seconds
        attempts = 0
        success = False
        
        # Validate we have tokens
        tokens = self.config.snipe.bearer_tokens
        if not tokens:
            logger.error("❌ No bearer tokens configured! Check your config.yaml")
            return SnipeResult(
                success=False,
                username=username,
                attempts=0,
                total_time=0.0,
                error_message="No bearer tokens configured"
            )
        
        # Dynamic concurrency: start with configured amount
        worker_count = self.config.snipe.concurrent_requests
        logger.info(f"🔥 Starting with {len(tokens)} tokens and {worker_count} workers")
        
        # Create workers - distributed across multiple tokens
        workers = []
        for i in range(worker_count):
            # Distribute workers evenly across available tokens
            token = tokens[i % len(tokens)]
            worker = asyncio.create_task(self._snipe_worker(username, stop_time, token))
            workers.append(worker)
        
        try:
            # Wait for workers
            results = await asyncio.gather(*workers, return_exceptions=True)
            
            # Aggregate statistics
            total_rate_limits = 0
            total_network_errors = 0
            
            # Process results
            for result in results:
                if isinstance(result, dict):
                    attempts += result.get('attempts', 0)
                    if result.get('success'):
                        success = True
                        logger.info(f"🎉 Successfully claimed username: {username}")
                    
                    # Aggregate error stats
                    errors = result.get('errors', {})
                    total_rate_limits += errors.get('rate_limits', 0)
                    total_network_errors += errors.get('network_errors', 0)
            
            # Log aggregate statistics
            logger.info(f"📊 Snipe statistics:")
            logger.info(f"   Total attempts: {attempts}")
            logger.info(f"   Rate limits hit: {total_rate_limits}")
            logger.info(f"   Network errors: {total_network_errors}")
            
            # Dynamic concurrency feedback (for next snipe)
            if total_rate_limits > attempts * 0.3:  # >30% rate limited
                suggested = max(worker_count // 2, len(tokens))
                logger.warning(f"⚠️ High rate limiting detected. Consider reducing concurrent_requests to {suggested}")
            elif total_rate_limits == 0 and attempts > 50:
                suggested = min(worker_count * 2, 20)
                logger.info(f"✅ No rate limits! You could increase concurrent_requests to {suggested}")
        
        except Exception as e:
            logger.error(f"Sniping error: {e}")
        
        total_time = time.time() - start_time
        
        return SnipeResult(
            success=success,
            username=username,
            attempts=attempts,
            total_time=total_time,
            error_message=None if success else "Failed to claim username"
        )
    
    async def _snipe_worker(self, username: str, stop_time: float, bearer_token: str = None) -> Dict[str, Any]:
        """Individual sniping worker with smart retry logic"""
        attempts = 0
        consecutive_failures = 0
        backoff_multiplier = 1.0
        worker_id = id(asyncio.current_task())
        token_info = f" (Token: ...{bearer_token[-8:]})" if bearer_token else ""
        
        # Error tracking for this worker
        error_stats = {
            'rate_limits': 0,
            'network_errors': 0,
            'server_errors': 0,
            'auth_errors': 0
        }
        
        logger.info(f"Worker {worker_id}{token_info} started sniping {username}")
        
        while time.time() < stop_time:
            try:
                result = await self._claim_username(username, bearer_token)
                attempts += 1
                self._connection_stats['requests_made'] += 1
                
                # Log progress every 10th attempt
                if attempts % 10 == 0:
                    logger.info(f"Worker {worker_id}: {attempts} attempts made")
                
                if result.get('success'):
                    logger.info(f"🎉 Worker {worker_id} SUCCESS after {attempts} attempts!")
                    logger.info(f"Worker {worker_id} stats: {error_stats}")
                    return {'success': True, 'attempts': attempts, 'errors': error_stats}
                
                # Smart error classification and retry logic
                status = result.get('status')
                
                if status == 429:  # Rate limited
                    error_stats['rate_limits'] += 1
                    retry_after = result.get('retry_after', 0.5)
                    
                    # Exponential backoff for rate limits (capped at max_backoff)
                    max_backoff = getattr(self.config.snipe, 'max_backoff_seconds', 5)
                    backoff_time = min(retry_after * backoff_multiplier, max_backoff)
                    backoff_multiplier = min(backoff_multiplier * 1.5, 3.0)  # Cap at 3x
                    
                    logger.warning(f"Worker {worker_id} rate limited, backing off {backoff_time:.2f}s")
                    await asyncio.sleep(backoff_time)
                    consecutive_failures += 1
                    
                elif status == 403:  # Forbidden (account cooldown or invalid token)
                    error_stats['auth_errors'] += 1
                    logger.warning(f"Worker {worker_id} hit auth error (403), waiting 2s")
                    await asyncio.sleep(2.0)
                    consecutive_failures += 1
                    
                elif status and status >= 500:  # Server error
                    error_stats['server_errors'] += 1
                    # Immediate retry for server errors (they're temporary)
                    logger.warning(f"Worker {worker_id} server error ({status}), immediate retry")
                    await asyncio.sleep(0.05)  # Tiny delay
                    consecutive_failures += 1
                    
                else:  # Success response or username taken
                    # Reset backoff on successful request (even if username taken)
                    backoff_multiplier = 1.0
                    consecutive_failures = 0
                    
                    # Use configured delay for normal requests
                    delay_seconds = self.config.snipe.request_delay_ms / 1000.0
                    await asyncio.sleep(delay_seconds)
                
                # Circuit breaker: if too many consecutive failures, increase delay
                if consecutive_failures > 10:
                    logger.warning(f"Worker {worker_id} circuit breaker: too many failures, pausing 1s")
                    await asyncio.sleep(1.0)
                    consecutive_failures = 0
                
            except asyncio.TimeoutError:
                error_stats['network_errors'] += 1
                logger.warning(f"Worker {worker_id} timeout, immediate retry")
                attempts += 1
                consecutive_failures += 1
                # Immediate retry for timeouts
                await asyncio.sleep(0.01)
                
            except aiohttp.ClientError as e:
                error_stats['network_errors'] += 1
                logger.error(f"Worker {worker_id} network error: {e}")
                attempts += 1
                consecutive_failures += 1
                # Short delay for network errors
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Worker {worker_id} unexpected error: {e}")
                attempts += 1
                consecutive_failures += 1
                await asyncio.sleep(0.1)
        
        logger.info(f"Worker {worker_id} finished with {attempts} attempts (no success)")
        logger.info(f"Worker {worker_id} final stats: {error_stats}")
        return {'success': False, 'attempts': attempts, 'errors': error_stats}
    
    async def _claim_username(self, username: str, bearer_token: str = None) -> Dict[str, Any]:
        """Try to claim a username with specified token"""
        # Safety check for session
        if not self.session:
            logger.error("HTTP session is None - cannot make request")
            return {'success': False, 'error': 'Session not initialized'}
        
        # Use provided token or fall back to primary token
        token = bearer_token or self.config.snipe.bearer_token
        
        url = f"https://api.minecraftservices.com/minecraft/profile/name/{username}"
        headers = {
            'Authorization': f'Bearer {token}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Get proxy for this request if proxy manager is available
        proxy = None
        if self.proxy_manager:
            try:
                proxy = await self.proxy_manager.get_proxy()
                if proxy:
                    logger.debug(f"Using proxy: {proxy}")
            except Exception as e:
                logger.warning(f"Failed to get proxy: {e}")
        
        try:
            # Track connection reuse (aiohttp reuses connections automatically with our connector)
            self._connection_stats['connections_reused'] += 1
            
            async with self.session.put(url, headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=2)) as response:
                response_text = await response.text()
                
                # Log detailed response for debugging
                proxy_info = f" via {proxy}" if proxy else " (direct)"
                logger.info(f"Claim attempt{proxy_info} - Status: {response.status}")
                
                if response.status == 200:
                    logger.info(f"🎉 SUCCESS! Claimed username: {username}")
                    logger.info(f"Response: {response_text}")
                    return {'success': True, 'response': response_text}
                elif response.status == 400:
                    logger.warning(f"Bad request (400) - Username might be taken or invalid")
                    logger.debug(f"Response: {response_text}")
                    return {'success': False, 'error': 'Bad request - username taken or invalid', 'status': 400}
                elif response.status == 401:
                    logger.error(f"Unauthorized (401) - Bearer token is invalid or expired")
                    logger.debug(f"Response: {response_text}")
                    return {'success': False, 'error': 'Invalid bearer token', 'status': 401}
                elif response.status == 403:
                    logger.warning(f"Forbidden (403) - Account on cooldown or username unavailable")
                    logger.debug(f"Response: {response_text}")
                    return {'success': False, 'error': 'Account on cooldown or username unavailable', 'status': 403}
                elif response.status == 404:
                    logger.error(f"Not found (404) - Account doesn't own Minecraft")
                    logger.debug(f"Response: {response_text}")
                    return {'success': False, 'error': 'Account does not own Minecraft', 'status': 404}
                elif response.status == 429:
                    # Extract retry-after header if present
                    retry_after = response.headers.get('Retry-After', '1')
                    try:
                        retry_seconds = float(retry_after)
                    except (ValueError, TypeError):
                        retry_seconds = 1.0
                    
                    logger.warning(f"Rate limited (429) - Backing off for {retry_seconds}s")
                    logger.debug(f"Response: {response_text}")
                    
                    # Record rate limit for this token
                    if hasattr(self, 'rate_limit_tracker') and token:
                        self.rate_limit_tracker.record_rate_limit(token, retry_seconds)
                    
                    # Return rate limit info for intelligent handling
                    return {
                        'success': False, 
                        'error': 'Rate limited', 
                        'status': 429,
                        'retry_after': retry_seconds
                    }
                else:
                    logger.warning(f"Unexpected status {response.status}: {response_text}")
                
                return {
                    'success': response.status == 200,
                    'status_code': response.status,
                    'username': username,
                    'response': response_text
                }
        except asyncio.TimeoutError:
            logger.warning(f"Timeout claiming {username}")
            return {'success': False, 'error': 'Request timeout', 'status': 'timeout'}
        except aiohttp.ClientError as e:
            logger.error(f"Network error claiming {username}: {e}")
            return {'success': False, 'error': f'Network error: {str(e)}', 'status': 'network_error'}
        except Exception as e:
            logger.error(f"Unexpected error claiming {username}: {e}")
            return {'success': False, 'error': str(e), 'status': 'unknown_error'}
    
    async def run_benchmark(self, duration: int = 5, requests: int = 10) -> Dict[str, float]:
        """Run a benchmark to test timing precision"""
        logger.info(f"📊 Starting benchmark: {requests} requests over {duration} seconds")
        
        results = []
        
        # Ensure high priority is set if enabled
        if self.config.performance.high_priority:
            try:
                p = psutil.Process(os.getpid())
                if sys.platform == "win32":
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
            except Exception:
                pass
        
        # Disable GC for benchmark accuracy
        if self.config.performance.gc_disable:
            gc.disable()
            
        try:
            try:
                # Try to sync time once BEFORE benchmark loop to avoid network jitter
                # This is optional - benchmark works fine with local time only
                await self.time_sync.sync_time()
                # Force last_sync to be very recent so it doesn't try again
                self.time_sync.last_sync = datetime.now(timezone.utc)
                logger.info("Time synced successfully for benchmark")
            except Exception as e:
                logger.warning(f"Time sync failed (network issue), using local time: {e}")
                # Benchmark will use local system time, which is fine for measuring timing precision
                self.time_sync.last_sync = datetime.now(timezone.utc)
            
            for i in range(requests):
                # Target time: 500ms from now (in Corrected Time domain)
                start_time = self.time_sync.get_accurate_time()
                target = start_time + timedelta(milliseconds=500)
                
                # Use our accurate timer
                await self.timer.wait_until(target, busy_wait_ms=self.config.performance.busy_wait_ms)
                
                # Measure "wake up" time immediately (in Corrected Time domain)
                actual = self.time_sync.get_accurate_time()
                
                # Calculate jitter (difference in microseconds)
                diff = (actual - target).total_seconds() * 1000 * 1000 # microseconds
                results.append(diff)
                
                logger.info(f"Measure {i+1}/{requests}: Offset {diff:.1f}μs")
                
                # Wait a bit before next measurement
                await asyncio.sleep(0.5)
                
        finally:
            if self.config.performance.gc_disable:
                gc.enable()
        
        if not results:
            return {}
            
        stats = {
            "count": len(results),
            "mean_offset_us": statistics.mean(results),
            "median_offset_us": statistics.median(results),
            "stdev_us": statistics.stdev(results) if len(results) > 1 else 0,
            "min_us": min(results),
            "max_us": max(results)
        }
        
        return stats
