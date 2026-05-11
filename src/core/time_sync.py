#!/usr/bin/env python3
"""
Time synchronization module for accurate sniping timing
"""

import time
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List

try:
    import ntplib
    _HAS_NTPLIB = True
except ImportError:
    _HAS_NTPLIB = False

logger = logging.getLogger(__name__)

class TimeSync:
    """Handles time synchronization for accurate sniping"""
    
    def __init__(self):
        self.time_offset = 0.0  # Offset from true time in seconds
        self.last_sync = None
        self.sync_sources = [
            "http://worldtimeapi.org/api/timezone/UTC",
            "https://timeapi.io/api/Time/current/zone?timeZone=UTC", 
            "http://worldclockapi.com/api/json/utc/now",
            # Additional fallback sources
            "https://worldtimeapi.org/api/timezone/UTC",  # HTTPS version
            "http://worldtimeapi.org/api/ip",  # Auto-detect timezone
        ]
    
    async def sync_time(self) -> bool:
        """Synchronize with internet time sources (multi-source with fallback)"""
        logger.info("🕐 Synchronizing time with internet sources...")
        
        offsets = []
        
        # Try NTP first - it's more reliable on VPS and works even when HTTP APIs are blocked
        ntp_offset = await asyncio.get_event_loop().run_in_executor(None, lambda: self._get_ntp_offset_sync())
        if ntp_offset is not None:
            offsets.append(ntp_offset)
            logger.debug(f"NTP offset: {ntp_offset:.3f}s")
        
        for source in self.sync_sources:
            try:
                offset = await self._get_time_offset(source)
                if offset is not None:
                    offsets.append(offset)
                    logger.debug(f"Time source {source}: offset {offset:.3f}s")
            except Exception as e:
                logger.debug(f"Could not reach time API {source}: {e}")
                continue
        
        if not offsets:
            # If all internet sources fail, use local system time as fallback
            # On a VPS the system clock is usually NTP-synced by the host, so this is fine
            logger.warning("⚠️ All internet time sources unreachable (likely firewall/network restriction on this VPS)")
            logger.warning("⚠️ Falling back to local system clock. On a VPS this is usually accurate (host NTP).")
            logger.warning("⚠️ If you see large timing errors, run: sudo ntpdate pool.ntp.org  OR  sudo timedatectl set-ntp true")
            
            # Set minimal offset (assume system time is reasonably accurate)
            self.time_offset = 0.0
            self.last_sync = datetime.now(timezone.utc)
            
            logger.info("✅ Fallback to local system time (offset: 0.000s)")
            return True
        
        # Outlier detection: use median if we have multiple sources
        if len(offsets) >= 2:
            offsets.sort()
            median_offset = offsets[len(offsets) // 2]
            
            # Reject outliers (>1s from median)
            filtered_offsets = [o for o in offsets if abs(o - median_offset) < 1.0]
            
            if filtered_offsets:
                self.time_offset = sum(filtered_offsets) / len(filtered_offsets)
                logger.info(f"✅ Time synced using {len(filtered_offsets)}/{len(offsets)} sources: offset {self.time_offset:.3f}s")
            else:
                self.time_offset = median_offset
                logger.warning(f"⏰ Time synced with outliers: offset {self.time_offset:.3f}s")
        else:
            # Single source
            self.time_offset = offsets[0]
            logger.info(f"✅ Time synchronized (offset: {self.time_offset:.3f}s)")
        
        self.last_sync = datetime.now(timezone.utc)
        
        if abs(self.time_offset) > 1.0:
            logger.warning(f"⚠️ System clock is {self.time_offset:.2f} seconds off!")
            logger.warning("Consider syncing your system clock with NTP")
        
        return True
    
    def _get_ntp_offset_sync(self) -> Optional[float]:
        """Synchronous wrapper for NTP offset - run in executor"""
        if not _HAS_NTPLIB:
            return None
        
        ntp_servers = [
            'pool.ntp.org',
            'time.cloudflare.com',
            'time.google.com',
            'time.windows.com',
        ]
        
        client = ntplib.NTPClient()
        for server in ntp_servers:
            try:
                response = client.request(server, version=3, timeout=3)
                return response.offset
            except Exception:
                continue
        return None

    def _parse_worldtimeapi(self, data: dict) -> Optional[datetime]:
        """Parse worldtimeapi.org response"""
        try:
            dt_str = data.get('utc_datetime') or data.get('datetime')
            if dt_str:
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.debug(f"Failed to parse worldtimeapi: {e}")
        return None
    
    def _parse_worldclockapi(self, data: dict) -> Optional[datetime]:
        """Parse worldclockapi.com response"""
        try:
            dt_str = data.get('currentDateTime')
            if dt_str:
                # Format: "2024-02-15T05:30Z"
                return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except Exception as e:
            logger.debug(f"Failed to parse worldclockapi: {e}")
        return None
    
    async def _get_time_offset(self, source: str) -> Optional[float]:
        """Get time offset from a specific source"""
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(source, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                network_delay = (time.time() - start_time) / 2  # Estimate one-way delay
                
                # Parse different API formats with robust handling
                server_time = None
                
                if 'utc_datetime' in data:  # worldtimeapi.org UTC endpoint
                    time_str = data['utc_datetime'].replace('Z', '+00:00')
                    try:
                        server_time = datetime.fromisoformat(time_str)
                    except ValueError:
                        # Handle microseconds precision issues
                        if '.' in time_str:
                            time_str = time_str.split('.')[0] + '+00:00'
                        server_time = datetime.fromisoformat(time_str)
                
                elif 'datetime' in data and 'utc_offset' in data:  # worldtimeapi.org IP endpoint
                    # Convert local time to UTC using offset
                    local_time_str = data['datetime']
                    utc_offset = data['utc_offset']  # Format: "+05:00" or "-05:00"
                    
                    try:
                        # Parse local time
                        if local_time_str.endswith('Z'):
                            local_time_str = local_time_str.replace('Z', '+00:00')
                        local_time = datetime.fromisoformat(local_time_str)
                        
                        # Parse UTC offset
                        offset_hours = int(utc_offset[:3])
                        offset_minutes = int(utc_offset[4:6]) if len(utc_offset) > 4 else 0
                        if utc_offset.startswith('-'):
                            offset_minutes = -offset_minutes
                        
                        total_offset = timedelta(hours=offset_hours, minutes=offset_minutes)
                        server_time = local_time - total_offset  # Convert to UTC
                    except (ValueError, IndexError):
                        return None
                
                elif 'dateTime' in data:  # timeapi.io
                    time_str = data['dateTime']
                    try:
                        # Handle high precision microseconds
                        if '.' in time_str and len(time_str.split('.')[1]) > 6:
                            # Truncate microseconds to 6 digits
                            parts = time_str.split('.')
                            microseconds = parts[1][:6]
                            time_str = f"{parts[0]}.{microseconds}"
                        
                        server_time = datetime.fromisoformat(time_str)
                        
                        # Ensure timezone aware - convert to UTC if needed
                        if server_time.tzinfo is None:
                            server_time = server_time.replace(tzinfo=timezone.utc)
                        elif server_time.tzinfo != timezone.utc:
                            server_time = server_time.astimezone(timezone.utc)
                            
                    except ValueError:
                        # Fallback: remove microseconds entirely
                        time_str = time_str.split('.')[0]
                        if not time_str.endswith('Z') and '+' not in time_str and '-' not in time_str[-6:]:
                            time_str += 'Z'
                        server_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                
                elif 'currentDateTime' in data:  # worldclockapi.com
                    time_str = data['currentDateTime']
                    try:
                        # Handle 'Z' suffix
                        if time_str.endswith('Z'):
                            time_str = time_str.replace('Z', '+00:00')
                        server_time = datetime.fromisoformat(time_str)
                    except ValueError:
                        # Fallback parsing
                        time_str = time_str.replace('Z', '')
                        server_time = datetime.fromisoformat(time_str + '+00:00')
                
                if server_time:
                    # Ensure both times are timezone-aware for comparison
                    if server_time.tzinfo is None:
                        server_time = server_time.replace(tzinfo=timezone.utc)
                    elif server_time.tzinfo != timezone.utc:
                        server_time = server_time.astimezone(timezone.utc)
                    
                    # Calculate offset accounting for network delay
                    local_time = datetime.now(timezone.utc)
                    offset = (server_time - local_time).total_seconds() - network_delay
                    return offset
        
        return None
    
    def get_accurate_time(self) -> datetime:
        """Get current time with offset correction"""
        current_time = datetime.now(timezone.utc)
        corrected_time = current_time + timedelta(seconds=self.time_offset)
        return corrected_time
    
    def should_resync(self) -> bool:
        """Check if time should be re-synchronized"""
        if not self.last_sync:
            return True
        
        # Resync every 30 minutes
        time_since_sync = datetime.now(timezone.utc) - self.last_sync
        return time_since_sync > timedelta(minutes=30)

class AccurateTimer:
    """High-precision timer for sniping"""
    
    def __init__(self, time_sync: TimeSync):
        self.time_sync = time_sync
    
    async def wait_until(self, target_time: datetime, callback=None, busy_wait_ms: int = 0):
        """Wait until exact target time with high precision"""
        logger.info(f"⏰ Waiting until: {target_time.isoformat()}")
        
        # Resync time if needed
        if self.time_sync.should_resync():
            await self.time_sync.sync_time()
        
        while True:
            current_time = self.time_sync.get_accurate_time()
            time_remaining = (target_time - current_time).total_seconds()
            
            if time_remaining <= 0:
                logger.info("🚨 TARGET TIME REACHED!")
                break
            
            # Call callback for countdown updates
            if callback:
                try:
                    await callback(time_remaining, current_time, target_time)
                except Exception as e:
                    logger.warning(f"Callback error: {e}")
            
            # Smart sleep intervals for accuracy with busy-wait support
            busy_wait_seconds = busy_wait_ms / 1000.0
            
            if time_remaining <= busy_wait_seconds:
                # 🚀 CRITICAL PHASE: Busy wait (Spin lock)
                # We interpret "time_remaining" relative to our own clock functions
                # To be super precise, we just stay in this loop checking time
                # blocking the event loop (which is what we want for 'pro' precision)
                while True:
                    if (target_time - self.time_sync.get_accurate_time()).total_seconds() <= 0:
                        break
                break # Break outer loop, we are done
                
            elif time_remaining > 60:
                sleep_time = min(10, time_remaining - 60)
            elif time_remaining > 10:
                 sleep_time = min(1, time_remaining - 10)
            else:
                # Approaching target. 
                # If we have a busy_wait buffer, we sleep until we hit that buffer.
                # But we need to account for OS sleep inaccuracy (~15ms on Windows).
                # So we aim to wake up 'safe_buffer' (e.g. 50ms) BEFORE the busy_wait phase starts.
                safe_buffer = 0.05
                time_to_busy_phase = time_remaining - busy_wait_seconds
                
                if time_to_busy_phase > safe_buffer:
                    sleep_time = time_to_busy_phase - safe_buffer
                else:
                    # We are extremely close to the busy wait phase but not quite there.
                    # Sleeping even 0 might overshoot if the OS scheduler is slow.
                    # Just yield to event loop briefly.
                    sleep_time = 0
            
            await asyncio.sleep(sleep_time)
    
    def calculate_drop_windows(self, base_drop_time: datetime, window_count: int = 5) -> List[datetime]:
        """Calculate multiple drop time windows to account for uncertainty"""
        windows: List[datetime] = []
        
        # Create windows: exact time, +0.1s, +0.2s, +0.5s, +1.0s
        offsets = [0.0, 0.1, 0.2, 0.5, 1.0]
        
        for i in range(min(window_count, len(offsets))):
            window_time = base_drop_time + timedelta(seconds=offsets[i])
            windows.append(window_time)
        
        return windows

# Test function
async def test_time_accuracy():
    """Test time synchronization accuracy"""
    print("🧪 Testing time synchronization...")
    
    time_sync = TimeSync()
    success = await time_sync.sync_time()
    
    if success:
        print(f"✅ Time sync successful!")
        print(f"   Offset: {time_sync.time_offset:.3f} seconds")
        print(f"   System time: {datetime.now(timezone.utc).isoformat()}")
        print(f"   Corrected time: {time_sync.get_accurate_time().isoformat()}")
    else:
        print("❌ Time sync failed!")
    
    return time_sync

if __name__ == "__main__":
    asyncio.run(test_time_accuracy())
