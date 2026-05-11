<div align="center">
<img width="2188" height="740" alt="download (12)" src="https://github.com/user-attachments/assets/c9ff5adc-7f55-45e2-bad1-11ac2c397dc0" />

Fast Minecraft username sniping with a simple CLI, token checks, proxy support, and precise drop timing.

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
</div>

<div align="center">

## 🪶 Recommended Proxies

[BirdProxies.com](https://www.birdproxies.com/@NAMEMCSNIPER)

Get 10% off + 15% extra data using the link above!

</div>

## What It Does

NameMC Sniper waits for a NameMC drop time, syncs timing as closely as possible, then sends Minecraft name-change requests during the claim window. It supports multiple bearer tokens, connection pooling, basic proxy rotation, Discord webhooks, and a menu mode if you do not want to use commands directly.

## Install

```bash
git clone https://github.com/zwroee/NameMcSniper.git
cd NameMcSniper
pip install -r requirements.txt
python Main.py config-create
```

Edit `config.yaml` after it is created. Do not commit your real `config.yaml` if it contains tokens, webhooks, or proxies.

## Run

Menu mode:

```bash
python menu.py
```

Command line:

```bash
python Main.py snipe-at -u "TargetName" -w "5/7/2026 • 6:06:50 PM"
```

The drop time format is:

```text
M/D/YYYY • H:MM:SS AM/PM
```

Copy it from NameMC exactly. Regular colons are supported, and the older `∶` colon style also works.

## Config

Keep the config conservative unless you have tested your setup.

```yaml
snipe:
  target_username: "TargetName"
  bearer_token: "your_minecraft_bearer_token"
  bearer_tokens:
    - "your_minecraft_bearer_token"
  concurrent_requests: 10
  request_delay_ms: 20
  max_snipe_attempts: 3000

performance:
  high_priority: true
  pre_warm_connections: true
  busy_wait_ms: 50

proxy:
  enabled: false
  proxies: []
```

Useful checks:

```bash
python Main.py test-token
python Main.py benchmark
python Main.py check-proxies
python Main.py config-validate
```

## Proxies

Use HTTP or HTTPS proxies in this format:

```text
http://username:password@host:port
http://host:port
```

Residential or ISP proxies are usually the best fit. Avoid free proxies and random datacenter lists; they are often slow, blocked, or already abused. SOCKS proxies are not recommended for this build unless you add proper SOCKS support, because the current request code is built around aiohttp's normal HTTP proxy handling.

For best results, test direct VPS latency first. A clean VPS connection can be faster than bad proxies. Only enable proxies if they are stable, low-latency, and pass `python Main.py check-proxies`.

## Notes

- Run on a machine with a correct system clock.
- More workers is not always better. Too many requests can trigger rate limits.
- More valid tokens helps more than spamming one token harder.
- If Linux cannot set high process priority, the sniper still runs; it just will not get the priority boost.

## VPS

A VPS is recommended for serious drops because it can stay online, keep a steady clock, and usually has better network stability than a home connection. If you do not have one, Oracle Cloud's free tier can work.

Oracle free VPS downsides:

- Setup is more annoying than a normal paid VPS.
- Free instances can be reclaimed or limited depending on availability.
- Network routing is not guaranteed to be the fastest for Minecraft services.
- ARM instances may need a little more package/setup patience.
- You still need to secure it, keep Python updated, and avoid committing secrets.

Test your latency and timing before relying on it for an important name.

## Legal

Use at your own risk. Respect Minecraft's terms, API limits, and account restrictions.
