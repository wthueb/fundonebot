# fundonebot

bitmex market bot
based on funding rate, with option for hedges in between positions

uses https://github.com/BitMEX/sample-market-maker framework

notes:
- cannot build sample-market-maker directly, there are changes to market_maker/market_maker.py, market_maker/bitmex.py, and market_maker/ws/ws_thread.py
- has stops implemented to prevent drastic losses in positions
- not particularly fast latency-wise, wouldn't be wise to adapt to quick trading strategies

### usage:
- install requirements.txt via pip
- change times in strat.py:main() to your local timezone (default is UTC, which should be fixed...)
- setup settings.py from settings_example.py with your api key and secret
	- modify variables in settings.py to desired values
- `python3 strat.py`

### TODO
- admin panel
- figure out commission/fees
- rewrite so we can "hook" ws updates instead of using FundingBot.monitor
    - get rid of sample-market-maker dependency
	- leads to faster reactions to price changes, etc
- figure out how to account for timezone re: scheduler
