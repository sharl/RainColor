# -*- coding: utf-8 -*-
#
# https://numberonebot.github.io/yeelight-client/
from typing import Any
import json
import socket

BLACK = (0, 0, 0)


class Lamp15:
    """
    Yeelight LED Screen Light Bar Pro (lamp15 / YLTD003) control
    """
    def __init__(self, host: str, port: int = 55443, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.left_rgb = BLACK
        self.right_rgb = BLACK
        self.sock = None
        self._id = 0

    def _connect(self):
        if not self.sock:
            self.sock = socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout,
            )

    def _command(self, method: str, params: list[Any]) -> Any:
        self._id += 1

        request = {
            'id': self._id,
            'method': method,
            'params': params,
        }

        data = (
            json.dumps(request, separators=(',', ':'))
            + '\r\n'
        ).encode('utf-8')

        if not self.sock:
            self._connect()

        try:
            self.sock.sendall(data)

            response = b''
            while b'\r\n' not in response:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                response += chunk

            if not response:
                return None

            return json.loads(response.split(b'\r\n', 1)[0])
        except Exception:
            self.sock.close()
            self.sock = None

    @staticmethod
    def _rgb(r: int, g: int, b: int) -> int:
        for value in (r, g, b):
            if not 0 <= value <= 255:
                raise ValueError('RGB values must be 0..255')

        return (r << 16) | (g << 8) | b

    # --- Front light -------------------------------------------------

    def front_on(self) -> Any:
        return self._command('set_power', ['on', 'sudden', 0])

    def front_off(self) -> Any:
        return self._command('set_power', ['off', 'sudden', 0])

    def front_brightness(self, brightness: int) -> Any:
        return self._command(
            'set_bright',
            [brightness, 'sudden', 0],
        )

    def front_ct(self, kelvin: int) -> Any:
        return self._command(
            'set_ct_abx',
            [kelvin, 'sudden', 0],
        )

    # --- Rear light --------------------------------------------------

    def rear_on(self) -> Any:
        return self._command('bg_set_power', ['on', 'sudden', 0])

    def rear_off(self) -> Any:
        return self._command('bg_set_power', ['off', 'sudden', 0])

    def rear_set_rgb(self, rgb: tuple[int, int, int]) -> Any:
        return self._command(
            'bg_set_rgb',
            [self._rgb(*rgb), self._rgb(*rgb)],
        )

    def rear_brightness(self, brightness: int) -> Any:
        return self._command(
            'bg_set_bright',
            [brightness, 'sudden', 0],
        )

    # --- Rear left / right ------------------------------------------
    SEGMENT_COLORS = [
        (0, 0, 1),      # blue
        (0, 1, 0),      # green
        (0, 1, 1),      # cyan
        (1, 0, 0),      # red
        (1, 0, 1),      # magenta
        (1, 1, 0),      # yellow
        (1, 1, 1),      # white
    ]

    def _round(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb

        least_d = float('inf')
        place = 0
        for i, (RR, GG, BB) in enumerate(self.SEGMENT_COLORS):
            d = (RR - r) ** 2 + (GG - g) ** 2 + (BB - b) ** 2
            if d < least_d:
                least_d = d
                place = i

        return self.SEGMENT_COLORS[place]

    def segments(
        self,
        left: tuple[int, int, int],
        right: tuple[int, int, int],
    ) -> Any:
        self.left_rgb = self._round(left)
        self.right_rgb = self._round(right)

        return self._command(
            'set_segment_rgb',
            [self._rgb(*left), self._rgb(*right)],
        )

    def set_left_rgb(self, left_rgb: tuple[int, int, int]) -> Any:
        return self.segments(left_rgb, self.right_rgb)

    def set_right_rgb(self, right_rgb: tuple[int, int, int]) -> Any:
        return self.segments(self.left_rgb, right_rgb)
