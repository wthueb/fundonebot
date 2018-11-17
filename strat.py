from datetime import datetime, timedelta
import os
import schedule
import signal
import sys
import threading
from time import sleep

from market_maker.market_maker import ExchangeInterface
from market_maker.utils import log

import settings
from utils import math


logger = log.setup_custom_logger('monitor')


class FundingBot:
    def __init__(self) -> None:
        self.exchange = ExchangeInterface()
        
        signal.signal(signal.SIGTERM, self.exit)

        self.start_balance = self.exchange.get_margin()['marginBalance'] / 100000000

        self.loop_count = 1

        self.start_time = datetime.now().isoformat(timespec='seconds') + 'Z'

        self.last_request = datetime.now()

        self.limits_exist = False

    def sanity_check(self) -> None:
        self.exchange.check_if_orderbook_empty()

        self.exchange.check_market_open()

    def print_status(self) -> None:
        position = self.exchange.get_position()
        ticker = self.exchange.get_ticker()
        current_balance = self.exchange.get_margin()['marginBalance'] / 100000000
        open_orders = self.exchange.bitmex.open_orders()

        logger.info('ticker buy: %.2f USD' % ticker['buy'])
        logger.info('ticker sell: %.2f USD' % ticker['sell'])

        current_quantity = position['currentQty']
        
        logger.info('current position: %i USD' % current_quantity)

        if current_quantity:
            average_entry_price = position['avgCostPrice']

            logger.info(' ~ average entry price: %.2f USD' % average_entry_price)

            original_value = current_quantity / average_entry_price
            
            logger.info(' ~ original position value: %.6f XBT' % original_value)

            current_value = self.exchange.calc_delta()['spot']

            logger.info(' ~ current position value: %.6f XBT' % current_value)

            value_delta = current_value - original_value

            logger.info(' ~ position value delta: %.6f XBT' % value_delta)

            profit = value_delta * (-ticker['buy'] if current_quantity < 0 else ticker['sell'])

            logger.info(' ~ position profit: %.2f USD' % profit)
        
        logger.info('starting XBT balance: %.6f XBT (%s)' % (self.start_balance, self.start_time))
        logger.info('current XBT balance: %.6f XBT' % current_balance)

        logger.info('open orders:%s' % (' none' if not open_orders else ''))

        for order in open_orders:
            if order['ordType'] == 'Limit':
                logger.info(' ~ limit order: %i @ %.2f USD' % (order['leavesQty'], order['price']))
            elif order['ordType'] == 'StopLimit':
                if order['orderQty']:
                    logger.info(' ~ stop limit order: %i, stop price: %.2f USD, price: %.2f USD' %
                                (order['orderQty'], order['stopPx'], order['price']))
                else:
                    logger.info(' ~ stop limit order: close, stop price: %.2f USD, price: %.2f USD' %
                                (order['stopPx'], order['price']))
            elif order['ordType'] == 'Stop':
                if order['orderQty']:
                    logger.info(' ~ stop order: %i, stop price: %.2f USD' %
                                (order['orderQty'], order['stopPx']))
                else:
                    logger.info(' ~ stop order: close, stop price: %.2f USD' % order['stopPx'])
        
        sys.stdout.write('----------\n')
        sys.stdout.flush()

    def get_price(self, side: str) -> float:
        ticker = self.exchange.get_ticker()
        
        if side.lower() not in ['buy', 'sell']:
            raise ValueError('invalid side passed to get_price: %s' % side)

        if side.lower() == 'buy':
            return ticker['sell'] - .5
        else:
            return ticker['buy'] + .5

    def monitor(self) -> None:
        """if the price moves negatively 1.5% away from a position, exit the position
        if there is an open order and the ticker moves, move the order
        """
        
        ticker = self.exchange.get_ticker()
        
        open_orders = self.exchange.bitmex.open_orders()

        to_amend = []
        
        for order in open_orders:
            if order['ordType'] != 'Limit':
                continue

            to_change = False

            if order['side'] == 'Buy':
                if order['price'] < self.get_price('buy'):
                    to_change = True
                    new_price = self.get_price('buy')
            else:
                if order['price'] > self.get_price('sell'):
                    to_change = True
                    new_price = self.get_price('sell')

            if to_change:
                to_amend.append({'orderID': order['orderID'],
                                 'orderQty': order['leavesQty'],
                                 'price': new_price, 'side': order['side']})

                logger.info('amending order %i from %.2f to %.2f' % (order['leavesQty'], order['price'], new_price))

        position = self.exchange.get_position()

        quantity = position['currentQty']

        if quantity:
            if not self.limits_exist:
                avg_price = position['avgCostPrice']

                if quantity > 0:
                    limit_stopPx = math.to_nearest(avg_price - avg_price*.015, .5)
                    limit_stop_price = limit_stopPx + .5

                    market_stopPx = math.to_nearest(avg_price - avg_price*.0175, .5)

                    side = 'Sell'
                else:
                    limit_stopPx = math.to_nearest(avg_price + avg_price*.015, .5)
                    limit_stop_price = limit_stopPx - .5

                    market_stopPx = math.to_nearest(avg_price + avg_price*.0175, .5)

                    side = 'Buy'

                limit_stop = {'stopPx': limit_stopPx, 'price': limit_stop_price,
                              'execInst': 'Close', 'ordType': 'StopLimit', 'side': side}

                market_stop = {'stopPx': market_stopPx, 'execInst': 'Close',
                               'ordType': 'Stop', 'side': side}
                
                self._create_orders([limit_stop, market_stop])

                self.limits_exist = True
        else:
            to_cancel = [o for o in open_orders if o['ordType'] in ['StopLimit', 'Stop']]

            if to_cancel:
                self._cancel_orders(to_cancel)

            self.limits_exist = False

        if to_amend:
            self._amend_orders(to_amend)

    def enter_position(self, side: str, trade_quantity: int, market=False) -> None:
        if market:
            logger.info('entering a position at market (%.2f): quantity: %i, side: %s' %
                        (self.exchange.get_ticker()[side.lower()], trade_quantity, side))

            order = {'type': 'Market', 'orderQty': trade_quantity, 'side': side}
        else:
            price = self.get_price(side)

            logger.info('entering a position ~ price: %.2f, quantity: %i, side: %s' %
                        (price, trade_quantity, side))

            order = {'price': price, 'orderQty': trade_quantity, 'side': side}

        self._create_orders([order])

    def exit_position(self, market=False, wait_for_fill=False) -> None:
        logger.info('exiting current position. at market: %s' % ('true' if market else 'false'))

        position = self.exchange.get_position()

        quantity = position['currentQty']

        if quantity == 0:
            logger.info(' ~ not currently in a position')
            return

        if quantity < 0:
            exit_side = 'Buy'
        else:
            exit_side = 'Sell'

        if market:
            order = {'type': 'Market', 'execInst': 'Close', 'side': exit_side}
        else:
            exit_price = self.get_price(exit_side)

            order = {'price': exit_price, 'execInst': 'Close', 'side': exit_side}

        self._create_orders([order])

        if wait_for_fill and not market:
            while True:
                sleep(10)

                postition = self.exchange.get_position()

                if position['currentQty'] == 0:
                    break

    def hedge(self, side: str, market=False) -> None:
        current_balance = self.exchange.get_margin()['marginBalance'] / 100000000

        logger.info('current balance: %.6f' % current_balance)
        
        if side not in ['Buy', 'Sell']:
            raise ValueError('side %s is not a valid side. options: Buy, Sell' % side)
        
        ticker = self.exchange.get_ticker()

        price = ticker[side.lower()]

        quantity = int(current_balance * settings.HEDGE_MULTIPLIER * price)

        logger.info('entering a hedge (at market: %s): %i @ %.2f' %
                    ('true' if market else 'false', quantity, price))

        if market:
            order = {'type': 'Market', 'orderQty': quantity, 'side': side}
        else:
            order = {'price': price, 'orderQty': quantity, 'side': side}

        self._create_orders([order])

    def cancel_open_orders(self) -> None:
        logger.info('cancelling all open orders')

        # saves an api request, as getting open orders is via the websocket
        open_orders = self.exchange.bitmex.open_orders()

        if not open_orders:
            logger.info(' ~ no open orders')
            return

        try:
            self.exchange.cancel_all_orders()
        except Exception as e:
            logger.error('unable to cancel orders: %s', e)
        
        self.limits_exist = False

    def exit(self, *args) -> None:
        logger.info('shutting down, all open orders will be cancelled')
        
        self.cancel_open_orders()
        
        #self.exit_position()
        
        self.exchange.bitmex.exit()

        sys.exit()

    def run_loop(self) -> None:
        while True:
            if not self.exchange.is_open():
                logger.error('realtime data connection has closed, reloading')

                self.reload()

            if (self.loop_count*settings.LOOP_INTERVAL) % 10 == 0:
                self.print_status()
                
                self.loop_count = 0

            self.loop_count += 1

            self.sanity_check()
            self.monitor()
            
            sleep(settings.LOOP_INTERVAL)

    def reload(self) -> None:
        logger.info('reloading data connection...')

        sleep(3)
        
        self.exchange = ExchangeInterface()

        sleep(3)

    def restart(self) -> None:
        logger.info('restarting funding bot...')

        os.execv(sys.executable, [sys.executable] + sys.argv)

    def get_instrument(self):
        return self.exchange.bitmex.instrument(symbol=settings.SYMBOL)

    def get_funding_rate(self) -> float:
        return self.get_instrument()['fundingRate']

    def respect_rate_limit(fn):
        def wrapped(self, *args, **kwargs):
            new_datetime = self.last_request + timedelta(seconds=settings.API_REST_INTERVAL)

            wait_time = (new_datetime - datetime.now()).total_seconds()

            if wait_time > 0:
                sleep(wait_time)

            return fn(self, *args, **kwargs)
        return wrapped

    @respect_rate_limit
    def _create_orders(self, orders) -> None:
        try:
            self.exchange.bitmex.create_bulk_orders(orders)
        except Exception as e:
            logger.warning('caught an error when requesting to the bitmex api: %s', e)

            logger.info('retrying request after 5 seconds...')

            sleep(5)

            self._create_orders(orders)

        self.last_request = datetime.now()

    @respect_rate_limit
    def _amend_orders(self, orders) -> None:
        try:
            self.exchange.bitmex.amend_bulk_orders(orders)
        except Exception as e:
            logger.warning('caught an error when requesting to the bitmex api: %s', e)

            if '400 Client Error' in str(e):
                logger.info(' ~ order has already been fulfilled')
            else:
                logger.info(' ~ retrying request after 5 seconds')

                sleep(5)

                self._amend_orders(orders)

        self.last_request = datetime.now()

    @respect_rate_limit
    def _cancel_orders(self, orders) -> None:
        for order in orders:
            try:
                self.exchange.cancel_order(order)
            except Exception as e:
                logger.error('unable to cancel order: %s' % e)

            sleep(settings.API_REST_INTERVAL)

        self.last_request = datetime.now()


def half_funding(bot: FundingBot) -> None:
    """4 hours until funding: enter a position
    if funding is negative, go long
    if funding is positive, go short
    """

    bot.exit_position(market=False, wait_for_fill=True)

    bot.cancel_open_orders()

    funding_rate = bot.get_funding_rate()

    logger.info('funding rate: %.6f' % funding_rate)

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


def run_scheduled() -> None:
    while True:
        schedule.run_pending()
        sleep(1)


def main() -> None:
    """place bitmex orders based on current funding rate

    if 4 hours until funding: enter a position
    if funding is negative, go long
    if funding is positive, go short
    if the price moves negatively 1.5% away from a position, exit the position
    if funding is over, exit all positions
    """

    bot = FundingBot()

    schedule.every().day.at('23:50').do(half_funding, bot)
    schedule.every().day.at('04:01').do(funding_over, bot)
    schedule.every().day.at('07:50').do(half_funding, bot)
    schedule.every().day.at('12:01').do(funding_over, bot)
    schedule.every().day.at('15:50').do(half_funding, bot)
    schedule.every().day.at('20:01').do(funding_over, bot)

    sched = threading.Thread(target=run_scheduled)

    sched.daemon = True
    
    sched.start()
    
    bot.run_loop()


if __name__ == '__main__':
    main()
