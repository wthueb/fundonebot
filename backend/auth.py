from hashlib import sha256
import hmac
import json
from time import time
from urllib.parse import urlparse

from requests.auth import AuthBase


class APIKeyAuthWithExpires(AuthBase):
    def __init__(self, key, secret):
        self.key = key
        self.secret = secret

    def __call__(self, r):
        expires = int(round(time() + 5))

        r.headers['api-expires'] = str(expires)
        r.headers['api-key'] = self.key
        r.headers['api-signature'] = generate_signature(self.secret, r.method, r.url,
                expires, r.body or '')

        return r


def generate_expires() -> int:
    return int(time() + 3600)


def generate_signature(secret, verb, url, nonce, data) -> str:
    parsed = urlparse(url)

    path = parsed.path

    if parsed.query:
        path = path + '?' + parsed.query

    if isinstance(data, (bytes, bytearray)):
        data = data.decode('utf8')

    message = verb + path + str(nonce) + data

    signature = hmac.new(bytes(secret, 'utf8'), bytes(message, 'utf8'),
            digestmod=sha256).hexdigest()

    return signature
