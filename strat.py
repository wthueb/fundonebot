import signal
import schedule
import threading
from time import sleep

from market_maker.utils import log

from bot import FundingBot
import settings


logger = log.setup_custom_logger('strat')


def half_funding(bot: FundingBot) -> None:
    """4 hours until funding: enter a position
    if funding is negative, go long
    if funding is positive, go short
    """

    bot.exit_position(market=False, wait_for_fill=True)

    bot.cancel_open_orders()

    funding_rate = bot.get_funding_rate()

    logger.info('funding rate: %.4f%%' % (funding_rate * 100))

    if funding_rate < 0:
        side = 'Buy'
    else:
        side = 'Sell'
    
    bot.enter_position(side, settings.TRADE_QUANTITY, market=False)


def funding_over(bot: FundingBot) -> None:
    """funding is over, exit all positions"""
    
    bot.exit_position(market=False, wait_for_fill=True)

    bot.cancel_open_orders()

    if settings.HEDGE:
        bot.hedge(settings.HEDGE_SIDE, market=False)


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

    schedule.every().day.at('23:50').do(half_funding, bot)
    schedule.every().day.at('04:01').do(funding_over, bot)
    schedule.every().day.at('07:50').do(half_funding, bot)
    schedule.every().day.at('12:01').do(funding_over, bot)
    schedule.every().day.at('15:50').do(half_funding, bot)
    schedule.every().day.at('20:01').do(funding_over, bot)

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
        logger.error('bot exiting with exception: %s' % str(e))

        bot.exit()


if __name__ == '__main__':
    main()
