from datetime import datetime
from dateutil import tz
import logging
import signal
import schedule
import threading
from time import sleep

from bot import FundingBot
import settings


logger = logging.getLogger()
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')

handler.setFormatter(formatter)

logger.addHandler(handler)

logger.setLevel(settings.LOG_LEVEL)


def half_funding(bot: FundingBot) -> None:
    """4 hours until funding: enter a position
    if funding is negative, go long
    if funding is positive, go short
    """

    bot.could_hedge = False

    bot.exit_position(market=False, wait_for_fill=True)

    bot.cancel_open_orders()

    funding_rate = bot.get_funding_rate()

    logger.info('funding rate: %.4f%%' % (funding_rate * 100))

    if funding_rate < 0:
        side = 'Buy'
        quantity = settings.POSITION_SIZE_BUY
    else:
        side = 'Sell'
        quantity = settings.POSITION_SIZE_SELL
    
    bot.enter_position(side, quantity, market=False)


def funding_over(bot: FundingBot) -> None:
    """funding is over, exit all positions"""

    sleep(1)
    
    bot.exit_position(market=False, wait_for_fill=True)


def main() -> None:
    """place bitmex orders based on current funding rate

    if 4 hours until funding: enter a position
    if funding is negative, go long
    if funding is positive, go short
    if the price moves negatively 1.5% away from a position, exit the position
    if funding is over, exit all positions
    """

    bot = FundingBot()

    signal.signal(signal.SIGTERM, bot.exit)
    signal.signal(signal.SIGINT, bot.exit)
    
    def convert_utc(utc_time : str) -> str:
        utc = datetime.strptime(utc_time, '%H:%M')

        utc = utc.replace(tzinfo=tz.tzutc())

        local = utc.astimezone(tz.tzlocal())

        return local.strftime('%H:%M')

    schedule.every().day.at(convert_utc('23:50')).do(half_funding, bot)
    schedule.every().day.at(convert_utc('04:00')).do(funding_over, bot)
    schedule.every().day.at(convert_utc('07:50')).do(half_funding, bot)
    schedule.every().day.at(convert_utc('12:00')).do(funding_over, bot)
    schedule.every().day.at(convert_utc('15:50')).do(half_funding, bot)
    schedule.every().day.at(convert_utc('20:00')).do(funding_over, bot)

    def run_scheduled() -> None:
        while True:
            schedule.run_pending()
            sleep(1)
    
    sched = threading.Thread(target=run_scheduled)
    sched.daemon = True
    sched.start()
    
    try:
        bot.run_loop()
    except Exception as e:
        logger.error('bot exiting with exception: %s' % e)

        import traceback

        traceback.print_exc()

        bot.exit()


if __name__ == '__main__':
    main()
