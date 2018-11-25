from datetime import datetime, timedelta
import os
import sys
from time import sleep

from market_maker.market_maker import ExchangeInterface
from market_maker.utils import log

import settings
from utils import math


class FundingBot:
    def __init__(self) -> None:
        self.logger = log.setup_custom_logger('fundingbot')
        
        self.exchange = ExchangeInterface()
        
        self.start_balance = self.exchange.get_margin()['marginBalance'] / 100000000

        self.loop_count = 1

        self.start_time = datetime.now().isoformat(timespec='seconds') + 'Z'

        self.last_request = datetime.now()

        self.limits_exist = False

        position = self.exchange.get_position()['currentQty']
        
        self.hedge_exists = position != 0 and abs(position) != settings.TRADE_QUANTITY
        self.could_hedge = position == 0

        self.cancel_open_orders()

    def sanity_check(self) -> None:
        self.exchange.check_if_orderbook_empty()

        self.exchange.check_market_open()

    def print_status(self) -> None:
        position = self.exchange.get_position()
        ticker = self.exchange.get_ticker()
        current_balance = self.exchange.get_margin()['marginBalance'] / 100000000
        open_orders = self.exchange.bitmex.open_orders()

        self.logger.info('ticker buy: %.2f USD' % ticker['buy'])
        self.logger.info('ticker sell: %.2f USD' % ticker['sell'])

        current_quantity = position['currentQty']
        
        self.logger.info('funding rate: %.4f%%' % (self.get_funding_rate() * 100))
        
        self.logger.info('current position: %i USD' % current_quantity)

        if current_quantity:
            average_entry_price = position['avgEntryPrice']

            self.logger.info(' ~ average entry price: %.2f USD' % average_entry_price)

            original_value = current_quantity / average_entry_price
            
            self.logger.info(' ~ original position value: %.6f XBT' % original_value)

            current_value = current_quantity / ticker['buy' if current_quantity > 0 else 'sell']

            self.logger.info(' ~ current position value: %.6f XBT' % current_value)

            value_delta = current_value - original_value

            self.logger.info(' ~ position value delta: %.6f XBT' % value_delta)

            profit = -value_delta * (ticker['buy'] if current_quantity < 0 else ticker['sell'])

            self.logger.info(' ~ position profit: %.2f USD' % profit)
        
        self.logger.info('starting XBT balance: %.6f XBT (%s)' %
                         (self.start_balance, self.start_time))

        self.logger.info('current XBT balance: %.6f XBT' % current_balance)

        self.logger.info('open orders:%s' % (' none' if not open_orders else ''))

        for order in open_orders:
            if order['ordType'] == 'Limit':
                self.logger.info(' ~ limit order: %i @ %.2f USD' %
                                 (order['leavesQty'], order['price']))
            elif order['ordType'] == 'StopLimit':
                if order['orderQty']:
                    self.logger.info((' ~ stop limit order: %i, stop price: %.2f USD, '
                                      'price: %.2f USD') % (order['orderQty'], order['stopPx'],
                                                            order['price']))
                else:
                    self.logger.info((' ~ stop limit order: close, stop price: %.2f USD, '
                                      'price: %.2f USD') % (order['stopPx'], order['price']))
            elif order['ordType'] == 'Stop':
                if order['orderQty']:
                    self.logger.info(' ~ stop order: %i, stop price: %.2f USD' %
                                (order['orderQty'], order['stopPx']))
                else:
                    self.logger.info(' ~ stop order: close, stop price: %.2f USD' %
                                     order['stopPx'])
        
        sys.stdout.write('-' * 20 + '\n')
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
                to_amend.append({'orderID': order['orderID'], 'price': new_price})

                self.logger.info('amending order %i from %.2f to %.2f' %
                            (order['leavesQty'], order['price'], new_price))
        
        if to_amend:
            self._amend_orders(to_amend)

        position = self.exchange.get_position()

        quantity = position['currentQty']

        if quantity:
            if not self.limits_exist and not self.hedge_exists:
                avg_price = position['avgEntryPrice']

                limit_delta = avg_price * settings.STOP_LIMIT_MULTIPLIER
                market_delta = avg_price * settings.STOP_MULTIPLIER

                if quantity > 0:
                    limit_stopPx = math.to_nearest(avg_price - limit_delta, .5)
                    limit_stop_price = limit_stopPx + .5

                    market_stopPx = math.to_nearest(avg_price - market_delta, .5)

                    side = 'Sell'
                else:
                    limit_stopPx = math.to_nearest(avg_price + limit_delta, .5)
                    limit_stop_price = limit_stopPx - .5

                    market_stopPx = math.to_nearest(avg_price + market_delta, .5)

                    side = 'Buy'

                limit_stop = {'stopPx': limit_stopPx, 'price': limit_stop_price,
                              'execInst': 'LastPrice,Close', 'ordType': 'StopLimit', 'side': side}

                market_stop = {'stopPx': market_stopPx, 'execInst': 'LastPrice,Close',
                               'ordType': 'Stop', 'side': side}
                
                self._create_orders([limit_stop, market_stop])

                self.limits_exist = True

            self.could_hedge = True
        else:
            to_cancel = [o for o in open_orders if o['ordType'] in ['StopLimit', 'Stop']]

            if to_cancel:
                self._cancel_orders(to_cancel)

            self.limits_exist = False

            if settings.HEDGE and not self.hedge_exists and self.could_hedge:
                self.hedge(settings.HEDGE_SIDE, market=False)

                self.hedge_exists = True

    def enter_position(self, side: str, trade_quantity: int, market=False) -> None:
        if market:
            self.logger.info('entering a position at market (%.2f): quantity: %i, side: %s' %
                        (self.exchange.get_ticker()[side.lower()], trade_quantity, side))

            order = {'type': 'Market', 'orderQty': trade_quantity, 'side': side}
        else:
            price = self.get_price(side)

            self.logger.info('entering a position ~ price: %.2f, quantity: %i, side: %s' %
                        (price, trade_quantity, side))

            order = {'price': price, 'orderQty': trade_quantity, 'side': side}

        self._create_orders([order])

        self.could_hedge = False

    def exit_position(self, market=False, wait_for_fill=False) -> None:
        self.logger.info('exiting current position. at market: %s' %
                         ('true' if market else 'false'))

        position = self.exchange.get_position()

        quantity = position['currentQty']

        if quantity == 0:
            self.logger.info(' ~ not currently in a position')
        
            self.hedge_exists = False
            self.could_hedge = True
            
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
                sleep(1)

                postition = self.exchange.get_position()

                if position['currentQty'] == 0:
                    break

        self.hedge_exists = False

    def hedge(self, side: str, market=False) -> None:
        current_balance = self.exchange.get_margin()['marginBalance'] / 100000000

        self.logger.info('current balance: %.6f' % current_balance)
        
        if side not in ['Buy', 'Sell']:
            raise ValueError('side %s is not a valid side. options: Buy, Sell' % side)
        
        ticker = self.exchange.get_ticker()

        price = ticker[side.lower()]

        quantity = int((current_balance-.1) * settings.HEDGE_MULTIPLIER * price)

        self.logger.info('entering a hedge (at market: %s): %i @ %.2f' %
                    ('true' if market else 'false', quantity, price))

        if market:
            order = {'type': 'Market', 'orderQty': quantity, 'side': side}
        else:
            order = {'price': price, 'orderQty': quantity, 'side': side}

        self._create_orders([order])
        
    def cancel_open_orders(self) -> None:
        self.logger.info('cancelling all open orders')

        # saves an api request, as getting open orders is via the websocket
        open_orders = self.exchange.bitmex.open_orders()

        if not open_orders:
            self.logger.info(' ~ no open orders')
            return

        try:
            self.exchange.cancel_all_orders()
        except Exception as e:
            self.logger.error('unable to cancel orders: %s', e)
        
        self.limits_exist = False

    def exit(self, *args) -> None:
        self.logger.info('shutting down, all open orders will be cancelled')
        
        self.cancel_open_orders()
        
        #self.exit_position()
        
        self.exchange.bitmex.exit()

        sys.exit()

    def run_loop(self) -> None:
        while True:
            if not self.exchange.is_open():
                self.logger.error('realtime data connection has closed, reloading')

                self.reload()

                return

            self.sanity_check()

            if (self.loop_count*settings.LOOP_INTERVAL) % 10 == 0:
                self.print_status()
                
                self.loop_count = 0

            self.loop_count += 1

            self.monitor()
            
            sleep(settings.LOOP_INTERVAL)

    def reload(self) -> None:
        self.logger.info('reloading data connection...')

        self.exchange = ExchangeInterface()

        sleep(3)

    def restart(self) -> None:
        self.logger.info('restarting funding bot...')

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
            self.logger.warning('caught an error when requesting to the bitmex api: %s', e)

            self.logger.info('retrying request after 5 seconds...')

            sleep(5)

            self._create_orders(orders)

        self.last_request = datetime.now()

    @respect_rate_limit
    def _amend_orders(self, orders) -> None:
        try:
            self.exchange.bitmex.amend_bulk_orders(orders)
        except Exception as e:
            self.logger.warning('caught an error when requesting to the bitmex api: %s', e)

            if '400 Client Error' in str(e):
                self.logger.info(' ~ order has already been fulfilled')
            else:
                self.logger.info(' ~ retrying request after 5 seconds')

                sleep(5)

                self._amend_orders(orders)

        self.last_request = datetime.now()

    @respect_rate_limit
    def _cancel_orders(self, orders) -> None:
        for order in orders:
            try:
                self.exchange.cancel_order(order)
            except Exception as e:
                self.logger.error('unable to cancel order: %s' % e)

            sleep(settings.API_REST_INTERVAL)

        self.last_request = datetime.now()
