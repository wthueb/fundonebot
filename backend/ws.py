import threading
import websocket


class BitmexWS:
    def connect(self, endpoint, should_auth=True) -> None:
        websocket.enableTrace(true)

        self.ws = websocket.WebSocketApp(url,
                on_open=,
                on_close=,
                on_message=,
                on_error=,
                header=)
