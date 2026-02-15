import os
import yaml
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from pathlib import Path

class ProxyConfig(BaseModel):
    """Configuration for proxy settings"""
    enabled: bool = False
    proxies: List[str] = Field(default_factory=list)
    rotation_enabled: bool = True
    timeout: int = 10
    max_retries: int = 3

class DiscordConfig(BaseModel):
    """Configuration for Discord notifications"""
    enabled: bool = False
    webhook_url: str = ""
    mention_role_id: str = ""
    embed_color: int = 0x00ff00
    
    # Optional bot token fields if used in the future
    bot_token: str = ""
    channel_id: str = ""

class SnipeConfig(BaseModel):
    """Snipe configuration"""
    target_username: str = ""
    target_uuid: str = ""
    bearer_token: str = ""
    bearer_tokens: List[str] = Field(default_factory=list)
    start_sniping_at_seconds: int = 0
    max_snipe_attempts: int = 3000
    request_delay_ms: int = 8
    concurrent_requests: int = 40
    
    # Rate limiting settings
    max_backoff_seconds: int = 5
    adaptive_delays: bool = True
    per_token_rate_limiting: bool = True
    
    @model_validator(mode='after')
    def validate_tokens(self) -> 'SnipeConfig':
        # If bearer_tokens is empty but we have bearer_token, add it
        if not self.bearer_tokens and self.bearer_token:
            self.bearer_tokens = [self.bearer_token]
            
        # If we have bearer_tokens but no single bearer_token, use the first one
        if self.bearer_tokens and not self.bearer_token:
            self.bearer_token = self.bearer_tokens[0]
            
        # Clean tokens
        if self.bearer_tokens:
            self.bearer_tokens = [t.strip() for t in self.bearer_tokens if t and t.strip()]
            
        # Warn if tokens are suspiciously short (but don't fail, maybe they are valid in some context)
        for i, token in enumerate(self.bearer_tokens):
            if len(token) < 50:
                print(f"⚠️ Warning: Token #{i+1} seems too short ({len(token)} chars)")
                
        return self

    @field_validator('concurrent_requests')
    @classmethod
    def validate_concurrent_requests(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("concurrent_requests must be greater than 0")
        return v

    @field_validator('request_delay_ms')
    @classmethod
    def validate_request_delay(cls, v: int) -> int:
        if v < 0:
            raise ValueError("request_delay_ms cannot be negative")
        return v

class NotificationSchedule(BaseModel):
    """Notification timing configuration"""
    intervals: List[int] = Field(default_factory=lambda: [
        86400, 43200, 21600, 7200, 3600, 1800, 300, 60, 30
    ])

class PerformanceConfig(BaseModel):
    """Performance optimization settings"""
    gc_disable: bool = True
    high_priority: bool = True
    pre_warm_connections: bool = True
    busy_wait_ms: int = 50
    
    @field_validator('busy_wait_ms')
    @classmethod
    def validate_busy_wait(cls, v: int) -> int:
        if v < 0: return 0
        if v > 1000: return 1000
        return v

class AppConfig(BaseModel):
    """Main application configuration"""
    snipe: SnipeConfig = Field(default_factory=SnipeConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    notifications: NotificationSchedule = Field(default_factory=NotificationSchedule)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    debug_mode: bool = False
    log_level: str = "INFO"

class ConfigManager:
    """Manages application configuration loading and saving"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.config = AppConfig()
    
    def load_config(self) -> AppConfig:
        """Load configuration from file"""
        if not self.config_path.exists():
            self.create_default_config()
            return self.config
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if data:
                # Pydantic handles nested validation automatically
                self.config = AppConfig(**data)
                # Now validate the loaded config
                # Pydantic validation happens on init, but we might want extra checks
                pass

            # Load proxies from file if enabled
            if self.config.proxy.enabled:
                self._load_proxies_from_file()

        except Exception as e:
            print(f"Error loading config: {e}")
            self.create_default_config()
        
        return self.config

    def _load_proxies_from_file(self):
        """Load proxies from proxies.txt if it exists"""
        proxy_file = Path("proxies.txt")
        if proxy_file.exists():
            try:
                with open(proxy_file, 'r', encoding='utf-8') as f:
                    file_proxies = [line.strip() for line in f if line.strip()]
                
                if file_proxies:
                    # Append or replace? Let's extend to be safe, or if config is empty, fill it.
                    # Common pattern: file overrides config.yaml for large lists
                    current_proxies = self.config.proxy.proxies or []
                    # distinct union
                    self.config.proxy.proxies = list(set(current_proxies + file_proxies))
                    print(f"Loaded {len(file_proxies)} proxies from {proxy_file}")
            except Exception as e:
                print(f"Warning: Failed to load proxies from file: {e}")
        else:
            # Create empty file if it doesn't exist so user knows where to put them
            try:
                with open(proxy_file, 'w', encoding='utf-8') as f:
                    f.write("# Add proxies here, one per line\n# Format: ip:port or user:pass@ip:port\n")
            except Exception:
                pass
    
    def save_config(self) -> None:
        """Save current configuration to file"""
        try:
            # model_dump is the V2 way, but let's stick to standard naming if possible or use dump
            # v2 uses model_dump(), v1 used dict()
            config_dict = self.config.model_dump()
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def create_default_config(self) -> None:
        """Create default configuration file"""
        self.config = AppConfig()
        self.save_config()
        print(f"Created default configuration file: {self.config_path}")
    
    def validate_config(self) -> List[str]:
        """
        Validate configuration and return list of errors.
        With Pydantic, most validation happens on load.
        This provides high-level business logic validation.
        """
        errors = []
        
        if not self.config.snipe.target_username:
            errors.append("Target username is required")
        
        if not self.config.snipe.bearer_token and not self.config.snipe.bearer_tokens:
            errors.append("Bearer token is required for Minecraft API authentication")
        
        if self.config.discord.enabled:
            if not self.config.discord.webhook_url and not self.config.discord.bot_token:
                errors.append("Discord webhook URL or bot token is required when Discord is enabled")
        
        if self.config.proxy.enabled and not self.config.proxy.proxies:
            errors.append("Proxy list is empty but proxy is enabled")
        
        return errors