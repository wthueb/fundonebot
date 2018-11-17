# fundonebot

bitmex market bot
based on funding rate, with option for hedges in between positions

### usage:
- install requirements.txt via pip
- change times in strat.py:main() to your local timezone (default is UTC)
- setup settings.py from settings_example.py with your api key and secret
	- modify variables in settings.py to desired values
- `python3 strat.py`

### TODO
- admin panel
- figure out commission/fees
- rewrite so we can "hook" ws updates instead of using FundingBot.monitor
	- leads to faster reactions to price changes, etc

