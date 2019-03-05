from base64 import b64encode
from datetime import datetime
import json
import logging
from time import sleep, time
from uuid import uuid4

import requests

from .auth import APIKeyAuthWithExpires
from .ws import BitmexWS


class ExchangeInterface:
    def __init__(self, api_key, api_secret, testnet=False,
                 oid_prefix='fundone_', timeout=10) -> None:
        self.logger = logging.getLogger(__name__)

        self.logger.setLevel(logging.INFO)
        
        self.API_KEY = api_key
        self.API_SECRET = api_secret
        
        if len(oid_prefix) > 13:
            raise ValueError('orderID prefix must be 13 characters or less')

        self.OID_PREFIX = oid_prefix

        self.session = requests.session()

        self.session.headers.update({'user-agent': 'fundonebot'})
        self.session.headers.update({'content-type': 'application/json'})
        self.session.headers.update({'accept': 'application/json'})

        self.ws = BitmexWS()

        self.ws.connect(self.API_KEY, self.API_SECRET, testnet=testnet)

        self.symbols = set()

        if testnet:
            self.BASE_URL = 'https://testnet.bitmex.com/api/v1/'
        else:
            self.BASE_URL = 'https://www.bitmex.com/api/v1/'

        self.retries = 0
        self.timeout = timeout

    def __del__(self) -> None:
        self.exit()

    def exit(self) -> None:
        self.ws.exit()

    def add_symbol(self, symbol):
        self.ws.add_symbol(symbol)

        self.symbols.add(symbol)

    def remove_symbol(self, symbol):
        self.ws.remove_symbol(symbol)

        self.symbols.remove(symbol)

    def ticker(self, symbol) -> dict:
        return self.ws.get_ticker(symbol)

    def instrument(self, symbol) -> dict:
        return self.ws.get_instrument(symbol)

    def auth_required(fn):
        def wrapped(self, *args, **kwargs):
            if not self.API_KEY:
                raise Exception('you must be authenticated to use this method')
            else:
                return fn(self, *args, **kwargs)

        return wrapped

    @auth_required
    def funds(self) -> dict:
        return self.ws.funds()

    @auth_required
    def position(self, symbol) -> dict:
        return self.ws.position(symbol)

    @auth_required
    def create_orders(self, orders : list) -> dict:
        for order in orders:
            order['clOrdID'] = (self.OID_PREFIX +
                    b64encode(uuid4().bytes).decode('utf8').rstrip('=\n'))

        return self._curl_bitmex(path='order/bulk', postdict={'orders': orders}, verb='POST')

    @auth_required
    def amend_orders(self, orders : list) -> dict:
        return self._curl_bitmex(path='order/bulk',
                postdict={'orders': orders}, verb='PUT', rethrow=True)

    @auth_required
    def open_orders(self) -> list:
        return self.ws.open_orders()

    @auth_required
    def cancel_order(self, oid) -> dict:
        return self._curl_bitmex(path='order', postdict={'orderID': oid}, verb='DELETE')

    @auth_required
    def _curl_bitmex(self, path, query=None, postdict=None, timeout=None, verb=None,
            rethrow=False, max_retries=None) -> dict:
        url = self.BASE_URL + path

        if timeout is None:
            timeout = self.timeout

        if not verb:
            verb = 'POST' if postdict else 'Get'

        if max_retries is None:
            max_retries = 0 if verb in ['POST', 'PUT'] else 3

        auth = APIKeyAuthWithExpires(self.API_KEY, self.API_SECRET)

        def exit_or_throw(e):
            if rethrow:
                raise e
            else:
                exit(1)

        def retry():
            self.retries += 1

            if self.retries > max_retries:
                raise Exception('max retries on %s (%s) hit' %
                        (path, json.dumps(postdict or '')))

            return self._curl_bitmex(path, query, postdict, timeout, verb, rethrow, max_retries)

        respone = None

        try:
            self.logger.info('sending request to %s: %s' %
                    (url, json.dumps(postdict or query or '')))

            req = requests.Request(verb, url, json=postdict, auth=auth, params=query)
            prepped = self.session.prepare_request(req)

            response = self.session.send(prepped, timeout=timeout)

            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if response is None:
                raise e

            if response.status_code == 401:
                self.logger.error('api key or secret is incorrect')
                self.logger.error('error: ' + response.text)

                if postdict:
                    self.logger.error(postdict)

                exit(1)
            elif response.status_code == 404:
                if verb == 'DELETE':
                    self.logger.error('order not found: %s' % postdict['orderID'])
                    return

                self.logger.error('unable to contact the bitmex api (404 not found)')
                self.logger.error('request: %s\n%s' % (url, json.dumps(postdict)))
                
                exit_or_throw(e)
            elif response.status_code == 429:
                self.logger.error('rate limited! sleeping and then trying again')
                self.logger.error('request: %s\n%s' % (url, json.dumps(postdict)))

                reset = response.headers['X-RateLimit-Reset']

                to_sleep = int(reset) - int(time())
                reset_str = datetime.fromtimestamp(int(reset)).strftime('%X')

                self.logger.warning('cancelling all known orders in the meantime')
                self.cancel([o['orderID'] for o in self.open_orders()])

                self.logger.error('rate limit will reset at %s, sleeping for %i seconds' %
                        (reset_str, to_sleep))

                sleep(to_sleep)

                return retry()
            elif response.status_code == 503:
                self.logger.warning('unable to contact the bitmex api (503 service unavailable)')
                self.logger.warning('request: %s\n%s' % (url, json.dumps(postdict)))
                self.logger.warning('retrying in 3 seconds')

                sleep(3)

                return retry()
            elif response.status_code == 400:
                error = response.json()['error']
                message = error['message'].lower() if error else ''

                if 'duplicate clordid' in message:
                    orders = postdict['orders'] if 'orders' in postdict else postdict

                    ids = json.dumps({'clOrdID': [order['clOrdID'] for order in orders]})

                    results = self._curl_bitmex('order', query={'filter': ids}, verb='GET')

                    for i, order in enumerate(results):
                        if (
                                order['orderQty'] != abs(postdict['orderQty']) or
                                order['side'] != ('Buy' if postdict['orderQty'] > 0 else 'Sell') or
                                order['price'] != postdict['price'] or
                                order['symbol'] != postdict['symbol']):
                            raise Exception('attempted to recover from duplicate clOrdID, ' +
                                    'but order did not match POST\n' +
                                    ('POST data: %s\n' % json.dumps(orders[i])) +
                                    ('returned order: %s' % json.dumps(order)))

                    return results
                elif 'insufficient available balance' in message:
                    self.logger.error('account out of funds')
                    self.logger.error(message)

                    exit_or_throw(Exception('insufficient funds'))

            self.logger.error('unhandled error: %s: %s' % (e, response.text))
            self.logger.error('request: %s %s: %s' % (verb, path, json.dumps(postdict)))

            exit_or_throw(e)
        except requests.exceptions.Timeout as e:
            self.logger.warning('timed out on request: %s (%s), retrying' %
                    (path, json.dumps(postdict or '')))

            return retry()
        except requests.exceptions.ConnectionError as e:
            self.logger.warning('unable to contact the bitmex api (%s). check the url' % e)
            self.logger.warning('retrying request: %s\n%s' % (url, json.dumps(postdict)))

            sleep(1)

            return retry()

        self.retries = 0

        return response.json()
