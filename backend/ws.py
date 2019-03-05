import json
import logging
from threading import Thread
from time import sleep, time

import websocket

from .auth import generate_expires, generate_signature


class BitmexWS:
    MAX_TABLE_LEN = 200

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

        self.logger.setLevel(logging.INFO)

        self._reset()
        
        self.symbols = set()

    def __del__(self) -> None:
        self.exit()

    def connect(self, api_key, api_secret, testnet=False) -> None:
        """ connect to ws with no subscriptions """
        self.API_KEY = api_key
        self.API_SECRET = api_secret

        if testnet:
            url = 'wss://testnet.bitmex.com/realtime'
        else:
            url = 'wss://www.bitmex.com/realtime'

        self.logger.info('connecting to %s' % url)

        self.logger.debug('starting thread')

        log = logging.getLogger('websocket')
        log.setLevel(logging.INFO)

        websocket.enableTrace(False)

        self.ws = websocket.WebSocketApp(url, header=self._get_auth_headers(),
                                              on_open=self._on_open,
                                              on_close=self._on_close,
                                              on_message=self._on_message,
                                              on_error=self._on_error)

        self.thread = Thread(target=lambda: self.ws.run_forever())
        self.thread.daemon = True
        self.thread.start()

        self.logger.info('started thread')

        timeout = 5

        while (not self.ws.sock or not self.ws.sock.connected) and timeout and not self._error:
            sleep(1)

            timeout -= 1

        if not timeout or self._error:
            self.logger.error('timed out when connecting to ws, restarting')

            self.restart()

        self.logger.info('connected to ws')

        args = ['margin', 'position']

        self._send_command('subscribe', args)

        while not {'margin', 'position'} <= set(self.data):
            sleep(.1)

        self.logger.info('got all necessary data, starting')

    def add_symbol(self, symbol) -> None:
        if symbol in self.symbols:
            raise ValueError('already subscribed to symbol: %s' % symbol)

        args = [sub + ':' + symbol for sub in ['instrument', 'quote',
                                               'trade', 'order', 'execution']]

        self._send_command('subscribe', args)

        # TODO: wait for partials
        sleep(5)

        self.symbols.add(symbol)

    def remove_symbol(self, symbol) -> None:
        if symbol not in self.symbols:
            raise ValueError('not subscribed to symbol: %s' % symbol)

        args = [sub + ':' + symbol for sub in ['instrument', 'quote',
                                               'trade', 'order', 'execution']]

        self._send_command('unsubscribe', args)

        self.symbols.remove(symbol)

    def get_instrument(self, symbol) -> dict:
        if symbol not in self.symbols:
            raise ValueError('not subscribed to symbol: %s' % symbol)

        instruments = self.data['instrument']

        matching = [i for i in instruments if i['symbol'] == symbol]

        if not matching:
            raise Exception('unable to find instrument with symbol: %s' % symbol)

        return matching[0]

    def get_ticker(self, symbol) -> dict:
        instrument = self.get_instrument(symbol)

        bid = instrument['bidPrice'] or instrument['lastPrice']
        ask = instrument['askPrice'] or instrument['lastPrice']

        ticker = {'last': instrument['lastPrice'],
                  'buy': bid,
                  'sell': ask,
                  'mid': (bid+ask) / 2 }

        return ticker

    def funds(self):
        return self.data['margin'][0]

    def open_orders(self, prefix=None) -> list:
        orders = self.data['order']

        if prefix:
            return [o for o in orders if str(o['clOrdID']).startswith(prefix) and
                    ('Close' in o['execInst'] or o['leavesQty'] > 0)]
        else:
            return [o for o in orders if 'Close' in o['execInst'] or o['leavesQty'] > 0]

    def position(self, symbol) -> dict:
        positions = self.data['position']

        pos = [p for p in positions if p['symbol'] == symbol]

        if not pos:
            return {'avgCostPrice': 0, 'avgEntryPrice': 0, 'currentQty': 0, 'symbol': symbol}

        return pos[0]

    def funds(self) -> dict:
        return self.data['margin'][0]

    def error(self, e) -> None:
        # TODO: handle errors/ping via pushbullet
        self._error = e

        self.logger.error(e)

        self.restart()

    def restart(self) -> None:
        # TODO
        self._reset()

    def exit(self) -> None:
        self.exited = True

        self.ws.close()

    def _on_open(self) -> None:
        self.logger.info('websocket opened')

    def _on_close(self) -> None:
        self.logger.info('websocket closed')

        self.exit()

    def _on_message(self, message) -> None:
        """ the important bit """
        message = json.loads(message)

        #self.logger.debug(json.dumps(message))

        try:
            if 'subscribe' in message:
                if message['success']:
                    self.logger.debug('subscribed to %s' % message['subscribe'])
                else:
                    self.error('unable to subscribe to %s. error: "%s"' %
                            (message['request']['args'][0], message['error']))

                return

            if 'status' in message:
                if message['status'] == 400:
                    self.error(message['error'])
                elif message['status'] == 401:
                    self.error('api key is incorrect')

                return

            if 'action' in message:
                table = message['table']

                if table not in self.data:
                    self.data[table] = []

                if table not in self.keys:
                    self.keys[table] = []
                
                action = message['action']

                # partial: full table image
                # insert: new row
                # update: update row
                # delete: delete row

                if action == 'partial':
                    #self.logger.debug('%s: partial' % table)

                    self.data[table] += message['data']

                    self.keys[table] = message['keys']
                elif action == 'insert':
                    #self.logger.debug('%s: inserting %s' % (table, message['data']))

                    self.data[table] += message['data']

                    # limit the max length of the table to save memory
                    if table not in ['order', 'orderBookL2']:
                        if len(self.data[table]) > BitmexWS.MAX_TABLE_LEN:
                            self.data[table] = self.data[table][(BitmexWS.MAX_TABLE_LEN // 2):]
                elif action == 'update':
                    #self.logger.debug('%s: updating %s' % (table, message['data']))

                    for data in message['data']:
                        item = find_by_keys(self.keys[table], self.data[table], data)

                        if not item:
                            continue

                        # log executions
                        # TODO: log them to a file as well
                        if table == 'order':
                            cancelled = 'ordStatus' in data and data['ordStatus'] == 'Canceled'

                            if 'cumQty' in data and not cancelled:
                                qty_exec = data['cumQty'] - item['cumQty']

                                if qty_exec > 0:
                                    instrument = self.get_instrument(item['symbol'])

                                    self.logger.info('execution: %s %d contracts of %s at %.*f' %
                                            (item['side'], qty_exec, item['symbol'],
                                                instrument['tickLog'], item['price']))

                        item.update(data)

                        if table == 'order' and item['leavesQty'] <= 0:
                            self.data[table].remove(item)
                elif action == 'delete':
                    #self.logger.debug('%s: deleting %s' % (table, message['data']))

                    for data in message['data']:
                        item = find_by_keys(self.keys[table], self.data[table], data)

                        self.data[table].remove(item)
                else:
                    raise Exception('unknown action: %s' % action)
        except:
            import traceback

            self.logger.error(traceback.format_exc())

    def _on_error(self, error) -> None:
        if not self.exited:
            self.error(error)

    def _send_command(self, op, args) -> None:
        command = json.dumps({'op': op, 'args': args or []})

        self.logger.debug('sending command: %s' % command)

        self.ws.send(command)

    def _reset(self) -> None:
        self.data = {}
        self.keys = {}
        self.exited = False
        self._error = None

    def _get_auth_headers(self) -> None:
        self.logger.info('authenticating with api key and secret')

        nonce = generate_expires()

        return ['api-expires: %s' % nonce,
                'api-signature: %s' % generate_signature(
                    self.API_SECRET, 'GET', '/realtime', nonce, ''),
                'api-key: %s' % self.API_KEY]


def find_by_keys(keys, table, data):
    for item in table:
        match = True

        for key in keys:
            if item[key] != data[key]:
                match = False

        if match:
            return item

    return None


if __name__ == '__main__':
    logger = logging.getLogger('ws')
    
    logger.setLevel(logging.DEBUG)

    sh = logging.StreamHandler()

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    sh.setFormatter(formatter)

    logger.addHandler(sh)

    ws = BitmexWS()
    ws.logger = logger

    ws.connect(api_key='JyrYsOppjM70sSIQ7cP4lvrl',
            api_secret='PnxQWArWsaJJYGKzASwVcHUeRkCJbPFi7BKfhxFNwO9V42B2', testnet=True)
