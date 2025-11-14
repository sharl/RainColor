# -*- coding: utf-8 -*-
import base64
import hashlib
import hmac
import json
import os
import platform
import time
import uuid

import requests

system = platform.system()
if system == 'Windows':
    CONF = os.environ.get('USERPROFILE', '.') + '/.SwitchBot'
else:
    CONF = os.environ.get('HOME') + '/.switchbot'


class SwitchBot:
    base_url = 'https://api.switch-bot.com'
    charset = 'utf-8'
    token = None
    secret = None

    def __init__(self):
        conf = CONF
        try:
            with open(conf) as fd:
                j = json.load(fd)
                self.token = j['token']
                self.secret = j['secret']
        except Exception as e:
            raise e

    def make_headers(self):
        nonce = uuid.uuid4()
        t = int(round(time.time() * 1000))
        string_to_sign = '{}{}{}'.format(self.token, t, nonce)

        string_to_sign = bytes(string_to_sign, self.charset)
        secret = bytes(self.secret, self.charset)
        sign = base64.b64encode(hmac.new(secret, msg=string_to_sign, digestmod=hashlib.sha256).digest())

        return {
            'Content-Type': 'application/json; charset={}'.format(self.charset),
            'Authorization': self.token,
            'sign': str(sign, self.charset),
            't': str(t),
            'nonce': str(nonce),
        }

    def get_device_list(self):
        headers = self.make_headers()
        with requests.get(f'{self.base_url}/v1.1/devices', headers=headers, timeout=10) as r:
            return json.loads(str(r.content, 'utf-8'))

        return []

    def parse(self, data):
        deviceType = data.get('deviceType')

        # have temp and humi sensors
        if deviceType in ['Meter', 'MeterPlus', 'WoIOSensor']:
            temperature = data['temperature']
            humidity = data['humidity']
            return '{}C {}%'.format(temperature, humidity)

        # have power status (lighting unit)
        if deviceType in ['Color Bulb']:
            # print(data)
            return data['power']

        # have power status (not lighting unit)
        if deviceType in ['Bot', 'Plug Mini (US)', 'Plug Mini (JP)', 'Plug']:
            return data['power']

        return None

    def get_device_status_raw(self, deviceID):
        headers = self.make_headers()
        with requests.get(f'{self.base_url}/v1.1/devices/{deviceID}/status', headers=headers, timeout=10) as r:
            return json.loads(str(r.content, 'utf-8')).get('body', {})
        return {}

    def get_device_status(self, deviceID):
        j = self.get_device_status_raw(deviceID)
        return self.parse(j)

    def post_command(self, deviceID, command, parameter='default', commandType='command'):
        headers = self.make_headers()
        with requests.post(f'{self.base_url}/v1.1/devices/{deviceID}/commands',
                           headers=headers,
                           json={
                               'command': command,
                               'parameter': str(parameter),
                               'commandType': commandType,
                           },
                           timeout=10):
            return 'ok'
        return 'ng'


if __name__ == '__main__':
    sb = SwitchBot()
    j = sb.get_device_list()
    print(json.dumps(j, indent=2, ensure_ascii=False))
