#!/usr/bin/env python3
"""
NameMC Sniper - CLI Minecraft Username Sniper
Monitors usernames via NameMC API and performs automated sniping with Discord notifications

Authors:
    - zwroe https://github.com/zwroee
    - light https://github.com/ZeroLight18
    
Created through collaborative development including pair programming sessions.
"""

import asyncio
import sys
import signal
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from src.config.config import ConfigManager, AppConfig
from src.core.sniper import UsernameSniper
from src.utils.logger import setup_logging, get_logger

console = Console()
logger = get_logger(__name__)

class NameMCSniper:
    """Main application class"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = None
        self.sniper = None
        self.running = False
    
    def load_config(self, config_path: str = "config.yaml") -> bool:
        """Load configuration from file"""
        try:
            self.config_manager.config_path = Path(config_path)
            self.config = self.config_manager.load_config()
            
            # Validate configuration
            errors = self.config_manager.validate_config()
            if errors:
                console.print("[red]Configuration errors found:[/red]")
                for error in errors:
                    console.print(f"  • {error}")
                return False
            
            return True
        except Exception as e:
            console.print(f"[red]Error loading config: {e}[/red]")
            return False
    
    def setup_logging(self):
        """Setup logging based on configuration"""
        log_file = f"logs/namemc_sniper_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        setup_logging(
            log_level=self.config.log_level,
            log_file=log_file,
            debug_mode=self.config.debug_mode
        )
    
    async def start_sniping(self):
        """Start the sniping process"""
        try:
            self.sniper = UsernameSniper(self.config)
            self.running = True
            
            # Setup signal handlers for graceful shutdown
            def signal_handler(signum, frame):
                logger.info("Received shutdown signal")
                self.running = False
                if self.sniper:
                    asyncio.create_task(self.sniper.stop_monitoring())
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Start monitoring
            await self.sniper.start_monitoring()
            
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Error in sniping process: {e}")
            console.print(f"[red]Error: {e}[/red]")
        finally:
            if self.sniper:
                await self.sniper.stop_monitoring()
            self.running = False
    
    def display_config_summary(self):
        """Display configuration summary"""
        table = Table(title="Configuration Summary", show_header=True, header_style="bold magenta")
        table.add_column("Setting", style="cyan", no_wrap=True)
        table.add_column("Value", style="green")
        
        table.add_row("Target Username", self.config.snipe.target_username)
        table.add_row("Bearer Token", "***" + self.config.snipe.bearer_token[-8:] if self.config.snipe.bearer_token else "Not set")
        table.add_row("Proxy Enabled", "Yes" if self.config.proxy.enabled else "No")
        table.add_row("Proxy Count", str(len(self.config.proxy.proxies)) if self.config.proxy.enabled else "0")
        table.add_row("Discord Enabled", "Yes" if self.config.discord.enabled else "No")
        table.add_row("Snipe Start Time", f"{self.config.snipe.start_sniping_at_seconds}s before drop")
        table.add_row("Max Attempts", str(self.config.snipe.max_snipe_attempts))
        table.add_row("Concurrent Requests", str(self.config.snipe.concurrent_requests))
        table.add_row("Request Delay", f"{self.config.snipe.request_delay_ms}ms")
        
        console.print(table)

@click.group()
@click.version_option(version="1.0.0", prog_name="NameMC Sniper")
def cli():
    """NameMC Sniper - CLI Minecraft Username Sniper"""
    pass

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
@click.option('--username', '-u', help='Target username to snipe')
@click.option('--token', '-t', help='Bearer token for authentication')
def snipe(config, username, token):
    """Start sniping a username"""
    app = NameMCSniper()
    
    # Load configuration
    if not app.load_config(config):
        sys.exit(1)
    
    # Override config with command line arguments
    if username:
        app.config.snipe.target_username = username
    if token:
        app.config.snipe.bearer_token = token
    
    # Validate required fields
    if not app.config.snipe.target_username:
        console.print("[red]Error: Target username is required[/red]")
        sys.exit(1)
    
    if not app.config.snipe.bearer_token:
        console.print("[red]Error: Bearer token is required[/red]")
        sys.exit(1)
    
    # Setup logging
    app.setup_logging()
    
    # Display configuration
    console.print(Panel.fit("🎯 NameMC Sniper Starting", style="bold green"))
    app.display_config_summary()
    
    # Start sniping
    try:
        asyncio.run(app.start_sniping())
    except KeyboardInterrupt:
        console.print("\n[yellow]Sniping interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def config_create(config):
    """Create a default configuration file"""
    config_manager = ConfigManager(config)
    config_manager.create_default_config()
    console.print(f"[green]Created default configuration file: {config}[/green]")
    console.print("[yellow]Please edit the configuration file with your settings before running the sniper.[/yellow]")

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def config_validate(config):
    """Validate configuration file"""
    config_manager = ConfigManager(config)
    
    try:
        app_config = config_manager.load_config()
        errors = config_manager.validate_config()
        
        if errors:
            console.print("[red]Configuration validation failed:[/red]")
            for error in errors:
                console.print(f"  • {error}")
            sys.exit(1)
        else:
            console.print("[green]Configuration is valid![/green]")
            
            # Display summary
            table = Table(title="Configuration Summary")
            table.add_column("Setting", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Target Username", app_config.snipe.target_username or "Not set")
            table.add_row("Bearer Token", "Set" if app_config.snipe.bearer_token else "Not set")
            table.add_row("Proxy Enabled", "Yes" if app_config.proxy.enabled else "No")
            table.add_row("Discord Enabled", "Yes" if app_config.discord.enabled else "No")
            
            console.print(table)
            
    except Exception as e:
        console.print(f"[red]Error validating config: {e}[/red]")
        sys.exit(1)

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def test_proxies(config):
    """Test proxy connections"""
    from src.network.proxy_manager import ProxyManager
    
    config_manager = ConfigManager(config)
    app_config = config_manager.load_config()
    
    if not app_config.proxy.enabled or not app_config.proxy.proxies:
        console.print("[yellow]No proxies configured[/yellow]")
        return
    
    async def run_test():
        proxy_manager = ProxyManager(
            proxy_list=app_config.proxy.proxies,
            rotation_enabled=app_config.proxy.rotation_enabled,
            timeout=app_config.proxy.timeout
        )
        
        console.print(f"[cyan]Testing {len(app_config.proxy.proxies)} proxies...[/cyan]")
        await proxy_manager.test_all_proxies()
        
        stats = proxy_manager.get_proxy_stats()
        
        table = Table(title="Proxy Test Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Total Proxies", str(stats['total_proxies']))
        table.add_row("Working Proxies", str(stats['working_proxies']))
        table.add_row("Failed Proxies", str(stats['bad_proxies']))
        table.add_row("Success Rate", f"{(stats['working_proxies']/stats['total_proxies']*100):.1f}%")
        table.add_row("Avg Response Time", f"{stats['average_response_time']:.2f}s")
        
        console.print(table)
    
    asyncio.run(run_test())


@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
@click.option('--username', '-u', required=True, help='Username to snipe')
@click.option('--drop-window', '-w', required=True, help='Drop window format: "9/29/2025 • 9∶04∶09 PM" (EXACT FORMAT REQUIRED)')
def snipe_at(config, username, drop_window):
    """Snipe a username at the specified time (starts 0.1s before, continues 10s after)"""
    config_manager = ConfigManager(config)
    app_config = config_manager.load_config()
    
    # Parse ONLY the exact drop window format: "9/29/2025 • 9∶04∶09 PM"
    try:
        from datetime import datetime, timezone, timedelta
        
        # Validate exact format first
        if '•' not in drop_window or '∶' not in drop_window:
            console.print(f"[red]Error: Invalid format. Must use EXACT format: '9/29/2025 • 9∶04∶09 PM'[/red]")
            console.print(f"[red]Your input: '{drop_window}'[/red]")
            console.print(f"[red]Required: bullet (•) and special colons (∶)[/red]")
            return
        
        # Clean up the format - replace special characters
        clean_window = drop_window.replace('•', '').replace('∶', ':').strip()
        
        # Try to parse the datetime - EXACT format only
        try:
            # Expected format after cleaning: "9/29/2025 9:04:09 PM"
            parsed_time = datetime.strptime(clean_window, '%m/%d/%Y %I:%M:%S %p')
        except ValueError:
            console.print(f"[red]Error: Invalid format. Must use EXACT format: '9/29/2025 • 9∶04∶09 PM'[/red]")
            console.print(f"[red]Your input: '{drop_window}'[/red]")
            console.print(f"[red]Expected: M/D/YYYY • H∶MM∶SS AM/PM[/red]")
            return
        # NameMC displays times in the user's local timezone
        # Convert from local timezone to UTC
        import time
        from datetime import datetime, timezone, timedelta
        
        # Get the user's local timezone offset
        local_offset_seconds = -time.timezone if time.daylight == 0 else -time.altzone
        local_offset = timedelta(seconds=local_offset_seconds)
        local_tz = timezone(local_offset)
        
        # Apply user's local timezone to parsed time
        parsed_time = parsed_time.replace(tzinfo=local_tz)
        parsed_time = parsed_time.astimezone(timezone.utc)
        
        # Check if time is in the future (allow 60 seconds grace period for clock drift)
        now = datetime.now(timezone.utc)
        grace_period = timedelta(seconds=60)
        if parsed_time <= (now - grace_period):
            console.print(f"[red]Error: Drop window time must be in the future.[/red]")
            console.print(f"[yellow]Current time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}[/yellow]")
            console.print(f"[yellow]Your time: {parsed_time.strftime('%Y-%m-%d %H:%M:%S UTC')}[/yellow]")
            console.print(f"[yellow]Tip: Your system clock may be slow. Try a time 1+ minutes in the future.[/yellow]")
            return
        
        time_until = (parsed_time - now).total_seconds()
        # Show both local and UTC times for clarity
        local_time = parsed_time.astimezone(local_tz)
        clean_display = drop_window.replace('•', ' ').replace('∶', ':')
        console.print(f"[green]SUCCESS[/green] Drop window parsed: {clean_display}")
        console.print(f"Local Time: {local_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
        console.print(f"UTC Time: {parsed_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        console.print(f"Time until drop: {time_until/3600:.2f} hours ({time_until:.0f} seconds)")
        
    except Exception as e:
        console.print(f"[red]Error parsing time: {e}[/red]")
        return
    
    async def run_snipe():
        console.print(f"[cyan]Starting sniper for username: {username}[/cyan]")
        console.print(f"[cyan]Drop time: {parsed_time.isoformat()}[/cyan]")
        console.print(f"[yellow]Sniping will start 0.1 seconds before drop time and continue for 10 seconds after[/yellow]")
        
        # Create and run sniper
        sniper = UsernameSniper(app_config)
        result = await sniper.snipe_at_time(parsed_time, username)
        
        # Display results
        if result.success:
            console.print(Panel.fit(
                f"SUCCESS! Claimed username '{username}' in {result.total_time:.2f}s with {result.attempts} attempts",
                style="bold green"
            ))
        else:
            console.print(Panel.fit(
                f"FAILED to claim '{username}'. Attempts: {result.attempts}, Time: {result.total_time:.2f}s\nError: {result.error_message or 'Unknown'}",
                style="bold red"
            ))
    
    asyncio.run(run_snipe())

@cli.command()
@click.option('--username', '-u', required=True, help='Username to snipe')
@click.option('--times', '-t', required=True, multiple=True, help='Drop times in NameMC format "M/D/YYYY • H∶MM∶SS AM/PM" (can specify multiple)')
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def snipe_fallback(username, times, config):
    """Snipe a username with multiple fallback drop times"""
    if len(times) < 2:
        console.print("[red]❌ Please provide at least 2 drop times for fallback sniping[/red]")
        console.print("[yellow]Example: python Main.py snipe-fallback -u Username -t \"12/25/2024 • 3∶30∶00 PM\" -t \"12/25/2024 • 3∶31∶00 PM\"[/yellow]")
        return
    
    # Load configuration
    config_manager = ConfigManager(config)
    try:
        app_config = config_manager.load_config()
    except Exception as e:
        console.print(f"[red]❌ Failed to load config: {e}[/red]")
        return
    
    # Override username in config
    app_config.snipe.target_username = username
    
    # Parse drop times using NameMC format
    drop_times = []
    for time_str in times:
        try:
            # Parse NameMC format: "9/30/2025 • 11∶46∶32 PM"
            if '•' not in time_str or '∶' not in time_str:
                console.print(f"[red]❌ Invalid NameMC format: '{time_str}'[/red]")
                console.print("[yellow]Use format: M/D/YYYY • H∶MM∶SS AM/PM[/yellow]")
                return
            
            # Clean the format: replace NameMC special characters
            import time as time_module
            from datetime import timedelta
            
            clean_window = time_str.replace('•', '').replace('∶', ':').strip()
            parsed_time = datetime.strptime(clean_window, '%m/%d/%Y %I:%M:%S %p')
            
            # NameMC displays times in the user's local timezone, convert to UTC
            # Get the user's local timezone offset
            local_offset_seconds = -time_module.timezone if time_module.daylight == 0 else -time_module.altzone
            local_offset = timedelta(seconds=local_offset_seconds)
            local_tz = timezone(local_offset)
            
            # Set as local time, then convert to UTC
            parsed_time = parsed_time.replace(tzinfo=local_tz)
            parsed_time = parsed_time.astimezone(timezone.utc)
            
            # Allow 60 second grace period for clock drift
            now = datetime.now(timezone.utc)
            grace_period = timedelta(seconds=60)
            if parsed_time <= (now - grace_period):
                console.print(f"[red]❌ Drop time '{time_str}' is in the past![/red]")
                console.print(f"[yellow]Tip: Your system clock may be slow. Try a time 1+ minutes in the future.[/yellow]")
                return
            
            drop_times.append(parsed_time)
        except ValueError:
            console.print(f"[red]❌ Invalid NameMC format: '{time_str}'[/red]")
            console.print("[yellow]Use format: M/D/YYYY • H∶MM∶SS AM/PM[/yellow]")
            console.print("[yellow]Example: 12/25/2024 • 3∶30∶00 PM[/yellow]")
            return
    
    # Sort drop times
    drop_times.sort()
    
    # Display summary
    console.print(f"[cyan]Fallback Snipe Configuration:[/cyan]")
    console.print(f"Username: [bold]{username}[/bold]")
    console.print(f"Drop Windows: [bold]{len(drop_times)}[/bold]")
    for i, dt in enumerate(drop_times, 1):
        console.print(f"  {i}. {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    async def run_fallback_snipe():
        console.print(f"[cyan]Starting fallback sniper for username: {username}[/cyan]")
        
        # Create and run sniper
        sniper = UsernameSniper(app_config)
        result = await sniper.snipe_with_fallback(drop_times, username)
        
        # Display results
        if result.success:
            console.print(Panel.fit(
                f"SUCCESS! Claimed username '{username}' using fallback system!",
                style="bold green"
            ))
        else:
            console.print(Panel.fit(
                f"FAILED to claim '{username}' after {len(drop_times)} drop windows.\nError: {result.error_message or 'All windows failed'}",
                style="bold red"
            ))
    
    asyncio.run(run_fallback_snipe())

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def test_token(config):
    """Test if your bearer token is valid"""
    config_manager = ConfigManager(config)
    app_config = config_manager.load_config()
    
    if not app_config.snipe.bearer_token or app_config.snipe.bearer_token == "your_minecraft_bearer_token_here":
        console.print("[red]❌ Bearer token not configured in config.yaml[/red]")
        return
    
    async def test_bearer_token():
        import aiohttp
        
        # Test token by getting current profile
        url = "https://api.minecraftservices.com/minecraft/profile"
        headers = {
            'Authorization': f'Bearer {app_config.snipe.bearer_token}',
            'User-Agent': 'MinecraftSniper/1.0'
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        profile_data = await response.json()
                        current_name = profile_data.get('name', 'Unknown')
                        console.print(f"[green]✅ Bearer token is valid![/green]")
                        console.print(f"[cyan]Current username: {current_name}[/cyan]")
                        console.print(f"[cyan]Account UUID: {profile_data.get('id', 'Unknown')}[/cyan]")
                    elif response.status == 401:
                        console.print(f"[red]❌ Bearer token is invalid or expired[/red]")
                        console.print(f"[yellow]Please get a new token from minecraft.net[/yellow]")
                    else:
                        response_text = await response.text()
                        console.print(f"[red]❌ Unexpected response: {response.status}[/red]")
                        console.print(f"[yellow]Response: {response_text}[/yellow]")
        except Exception as e:
            console.print(f"[red]❌ Error testing token: {e}[/red]")
    
    asyncio.run(test_bearer_token())

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
@click.option('--output', '-o', default='proxies_working.txt', help='Output file for working proxies')
@click.option('--concurrency', default=50, help='Number of concurrent checks', type=int)
def check_proxies(config, output, concurrency):
    """Check and validate all configured proxies"""
    try:
        console.print(f"[dim]Debug: Loading config from {config}[/dim]")
        config_manager = ConfigManager(config)
        app_config = config_manager.load_config()
        
        console.print(f"[dim]Debug: Config loaded. Proxy enabled: {app_config.proxy.enabled}[/dim]")
        
        if not app_config.proxy.enabled or not app_config.proxy.proxies:
            console.print("[red]❌ Proxies are not enabled or list is empty[/red]")
            return
            
        proxies = app_config.proxy.proxies
        console.print(f"[dim]Debug: Proxies type: {type(proxies)}, Len: {len(proxies)}[/dim]")

        console.print(Panel.fit(
            f"🚀 Starting Proxy Checker\n"
            f"proxies: [bold]{len(proxies)}[/bold]\n"
            f"Threads: [bold]{concurrency}[/bold]",
            title="Proxy Checker",
            border_style="cyan"
        ))
        
        async def run_check():
            from src.network.proxy_checker import ProxyChecker
            checker = ProxyChecker(app_config)
            
            with console.status(f"[bold green]Checking {len(proxies)} proxies...[/bold green]"):
                results = await checker.check_all(max_concurrent=concurrency)
                
            alive = [r for r in results if r['status'] == 'alive']
            dead = [r for r in results if r['status'] != 'alive']
            
            # Display results
            console.print(f"\n[bold green]✅ Working: {len(alive)}[/bold green]")
            console.print(f"[bold red]❌ Dead: {len(dead)}[/bold red]")
            
            if alive:
                # Calculate stats
                if any(r['latency_ms'] for r in alive):
                    avg_latency = sum(r['latency_ms'] for r in alive) / len(alive)
                    console.print(f"[cyan]Average Latency: {avg_latency:.1f}ms[/cyan]")
                
                # Save working proxies
                try:
                    with open(output, 'w', encoding='utf-8') as f:
                        for r in alive:
                            f.write(f"{r['proxy']}\n")
                    console.print(f"[green]💾 Saved {len(alive)} working proxies to {output}[/green]")
                except Exception as e:
                    console.print(f"[red]Failed to save output: {e}[/red]")
            else:
                console.print("[yellow]⚠️ No working proxies found![/yellow]")

        asyncio.run(run_check())
        
    except Exception as e:
        console.print(f"[bold red]❌ Critical Error in check_proxies: {e}[/bold red]")
        import traceback
        traceback.print_exc()

@cli.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def check_accounts(config):
    """Validate all configured bearer tokens"""
    config_manager = ConfigManager(config)
    app_config = config_manager.load_config()
    
    tokens = app_config.snipe.bearer_tokens
    
    if not tokens:
        console.print("[red]❌ No bearer tokens configured[/red]")
        return
        
    console.print(Panel.fit(
        f"🚀 Starting Account Validator\n"
        f"Tokens to check: [bold]{len(tokens)}[/bold]",
        title="Account Validator",
        border_style="cyan"
    ))
    
    async def run_check():
        from src.core.account_checker import AccountValidator
        validator = AccountValidator(app_config)
        
        with console.status(f"[bold green]Checking {len(tokens)} tokens...[/bold green]"):
            results = await validator.check_all()
            
        valid = [r for r in results if r['valid']]
        invalid = [r for r in results if not r['valid']]
        
        console.print(f"\n[bold green]✅ Valid: {len(valid)}[/bold green]")
        console.print(f"[bold red]❌ Invalid: {len(invalid)}[/bold red]")
        
        # Determine max name length for padding
        max_name_len = max([len(r.get('name', '')) for r in valid]) if valid else 0
        max_name_len = max(max_name_len, 4) # min 4 chars
        
        if valid:
            console.print("\n[u]Valid Accounts:[/u]")
            for r in valid:
                console.print(f"  [green]• {r.get('name'):<{max_name_len}}[/green] [dim]({r.get('masked')})[/dim]")
                
        if invalid:
            console.print("\n[u]Invalid Tokens:[/u]")
            for r in invalid:
                console.print(f"  [red]• {r.get('masked')}[/red] - {r.get('error')}")

    asyncio.run(run_check())

@cli.command()
def version():
    """Show version information"""
    console.print(Panel.fit(
        Text("NameMC Sniper v2.0.0\nMinecraft Username Sniper with Drop Window Estimation", justify="center"),
        style="bold blue"
    ))

@cli.command()
@click.option('--requests', '-r', default=10, help='Number of benchmark requests')
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
def benchmark(requests, config):
    """Run a timing benchmark to test system precision"""
    config_manager = ConfigManager(config)
    app_config = config_manager.load_config()
    
    sniper = UsernameSniper(app_config)
    
    console.print(Panel.fit(
        f"🚀 Running Timing Benchmark\n"
        f"High Priority: {app_config.performance.high_priority}\n"
        f"GC Disabled: {app_config.performance.gc_disable}\n"
        f"Busy Wait: {app_config.performance.busy_wait_ms}ms",
        title="Benchmark",
        style="bold magenta"
    ))
    
    async def run():
        stats = await sniper.run_benchmark(requests=requests)
        
        if not stats:
            console.print("[red]Benchmark failed to produce results[/red]")
            return
            
        table = Table(title="Benchmark Results (Microseconds)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Mean Offset", f"{stats['mean_offset_us']:.1f} μs")
        table.add_row("Median Offset", f"{stats['median_offset_us']:.1f} μs")
        table.add_row("Jitter (StdDev)", f"{stats['stdev_us']:.1f} μs")
        table.add_row("Max Offset", f"{stats['max_us']:.1f} μs")
        
        console.print(table)
        
        # Rating
        jitter = stats['stdev_us']
        if jitter < 100:
            rating = "[bold green]EXCELLENT (Pro Level)[/bold green]"
        elif jitter < 1000:
            rating = "[bold yellow]GOOD (Competitive)[/bold yellow]"
        else:
            rating = "[bold red]POOR (Optimization Needed)[/bold red]"
            
        console.print(f"\nSystem Rating: {rating}")
        console.print("[dim]Note: Lower offset/jitter is better. 1000μs = 1ms[/dim]")

    asyncio.run(run())

if __name__ == "__main__":
    cli()