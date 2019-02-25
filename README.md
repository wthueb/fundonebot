# fundonebot

bitmex market bot
based on funding rate, with option for hedges in between positions

### notes:
- has stops implemented to prevent drastic losses in positions

### usage:
- setup settings.py from settings_example.py with your api key and secret
	- modify variables in settings.py to desired values
- `pip3 install -r requirements.txt`
- `python3 strat.py`

### TODO:
- figure out commission/fees
