import base64
from datetime import datetime
import json
import logging
import time

import requests

from .ws import BitmexWS


class ExchangeInterface:
    def __init__(self, api_key, api_secret, testnet=False,
                 oid_prefix='fundone_', timeout=10) -> None:
        self.logger = logging.getLogger('exchange')
        
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

        self.retries = 0
        self.timeout = timeout
