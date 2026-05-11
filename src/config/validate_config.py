#!/usr/bin/env python3
"""
Configuration validator for NameMC Sniper
"""

import yaml
import sys
from pathlib import Path
from src.config.config import ConfigManager

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def validate_config(config_path: str = "config.yaml"):
    """Validate sniper configuration"""
    print("🔍 Validating NameMC Sniper Configuration")
    print("=" * 50)
    
    config_file = Path(config_path)
    
    # Check if config file exists
    if not config_file.exists():
        print(f"❌ Config file not found: {config_path}")
        print("💡 Run 'python Main.py config-create' to create one")
        return False
    
    try:
        # Load raw YAML first to debug
        with open(config_file, 'r') as f:
            raw_config = yaml.safe_load(f)
        
        print(f"✅ Config file loaded successfully")
        
        # Check if snipe section exists
        if 'snipe' not in raw_config:
            print(f"❌ No 'snipe' section found in config")
            return False
        
        snipe_raw = raw_config['snipe']
        
        # Check for bearer tokens
        bearer_token = snipe_raw.get('bearer_token', '')
        bearer_tokens = snipe_raw.get('bearer_tokens', [])
        
        if not bearer_token and not bearer_tokens:
            print(f"❌ No bearer tokens found in config")
            print(f"   bearer_token: '{bearer_token}'")
            print(f"   bearer_tokens: {bearer_tokens}")
            return False
        
        # Now try to load with ConfigManager
        config_manager = ConfigManager(config_path)
        config = config_manager.load_config()
        errors = config_manager.validate_config()
        if errors:
            print(f"\n❌ Configuration errors:")
            for error in errors:
                print(f"   • {error}")
            return False
        
        # Validate snipe configuration
        snipe_config = config.snipe
        
        print(f"\n📊 Configuration Summary:")
        print(f"   Tokens: {len(snipe_config.bearer_tokens)}")
        print(f"   Workers: {snipe_config.concurrent_requests}")
        print(f"   Delay: {snipe_config.request_delay_ms}ms")
        print(f"   Max Attempts: {snipe_config.max_snipe_attempts}")
        
        # Validate tokens
        print(f"\n🔑 Token Validation:")
        for i, token in enumerate(snipe_config.bearer_tokens, 1):
            if len(token) < 50:
                print(f"   ⚠️ Token #{i}: Seems too short ({len(token)} chars)")
            else:
                print(f"   ✅ Token #{i}: Valid length (...{token[-8:]})")
        
        # Performance warnings
        print(f"\n⚡ Performance Analysis:")
        
        if snipe_config.concurrent_requests > 50:
            print(f"   ⚠️ High worker count ({snipe_config.concurrent_requests}) - may cause rate limiting")
        elif snipe_config.concurrent_requests < 10:
            print(f"   💡 Low worker count ({snipe_config.concurrent_requests}) - consider increasing for better performance")
        else:
            print(f"   ✅ Worker count looks good ({snipe_config.concurrent_requests})")
        
        if snipe_config.request_delay_ms < 5:
            print(f"   ⚠️ Very low delay ({snipe_config.request_delay_ms}ms) - high risk of rate limiting")
        elif snipe_config.request_delay_ms > 50:
            print(f"   💡 High delay ({snipe_config.request_delay_ms}ms) - may reduce competitiveness")
        else:
            print(f"   ✅ Request delay looks balanced ({snipe_config.request_delay_ms}ms)")
        
        # Calculate theoretical performance
        tokens_count = len(snipe_config.bearer_tokens)
        workers_per_token = snipe_config.concurrent_requests / tokens_count
        requests_per_second = (1000 / snipe_config.request_delay_ms) * snipe_config.concurrent_requests
        
        print(f"\n📈 Theoretical Performance:")
        print(f"   Workers per token: {workers_per_token:.1f}")
        print(f"   Requests per second: {requests_per_second:.1f}")
        
        if requests_per_second > 200:
            print(f"   ⚠️ Very high request rate - expect rate limiting")
        elif requests_per_second < 50:
            print(f"   💡 Conservative request rate - safe but may be slow")
        else:
            print(f"   ✅ Good request rate for competitive sniping")
        
        # Discord validation
        if config.discord.enabled:
            if config.discord.webhook_url:
                print(f"\n📢 Discord: ✅ Configured")
            else:
                print(f"\n📢 Discord: ❌ Enabled but no webhook URL")
        else:
            print(f"\n📢 Discord: ⚪ Disabled")
        
        # Proxy validation
        if config.proxy.enabled:
            if config.proxy.proxies:
                print(f"\n🌐 Proxies: ✅ {len(config.proxy.proxies)} configured")
            else:
                print(f"\n🌐 Proxies: ❌ Enabled but no proxies listed")
        else:
            print(f"\n🌐 Proxies: ⚪ Disabled")
        
        print(f"\n✅ Configuration validation completed successfully!")
        return True
        
    except ValueError as e:
        print(f"❌ Configuration error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def suggest_optimizations(config_path: str = "config.yaml"):
    """Suggest configuration optimizations"""
    print(f"\n💡 Optimization Suggestions:")
    
    try:
        config_manager = ConfigManager(config_path)
        config = config_manager.load_config()
        snipe_config = config.snipe
        
        # Token suggestions
        if len(snipe_config.bearer_tokens) == 1:
            print(f"   🔑 Consider adding more tokens to compete with multi-account snipers")
        
        # Performance suggestions based on token count
        token_count = len(snipe_config.bearer_tokens)
        optimal_workers = min(token_count * 15, 60)  # 15 workers per token, max 60
        optimal_delay = max(8, 100 // token_count)  # Faster with more tokens
        
        if snipe_config.concurrent_requests != optimal_workers:
            print(f"   ⚡ Optimal workers for {token_count} tokens: {optimal_workers} (current: {snipe_config.concurrent_requests})")
        
        if snipe_config.request_delay_ms != optimal_delay:
            print(f"   ⏱️ Optimal delay for {token_count} tokens: {optimal_delay}ms (current: {snipe_config.request_delay_ms}ms)")
        
        # Infrastructure suggestions
        print(f"   🏗️ For best performance:")
        print(f"      - Use VPS with <100ms latency to Minecraft servers")
        print(f"      - Consider residential proxies for better routing")
        print(f"      - Sync system clock with NTP")
        
    except Exception as e:
        print(f"   ❌ Could not generate suggestions: {e}")

if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    
    if validate_config(config_file):
        suggest_optimizations(config_file)
    else:
        sys.exit(1)
