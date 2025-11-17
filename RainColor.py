# -*- coding: utf-8 -*-
from configparser import ConfigParser
import ctypes
import datetime as dt
import io
import logging
import logging.handlers
import math
import os
import threading
import time
import webbrowser

from PIL import Image, ImageDraw
from SwitchBot import SwitchBot
from bs4 import BeautifulSoup
from pystray import Icon, Menu, MenuItem
from vvox import vvox
from yeelight import discover_bulbs, Bulb
import darkdetect as dd
import netifaces as netif
import requests
import schedule

NAME = 'Yeelight Rain Color'

INTERVAL = 5 * 60
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
PreferredAppMode = {
    'Light': 0,
    'Dark': 1,
}
# https://github.com/moses-palmer/pystray/issues/130
ctypes.windll['uxtheme.dll'][135](PreferredAppMode[dd.theme()])


# logger settings
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler("log.log", encoding='utf-8', maxBytes=1000000, backupCount=0),
        logging.StreamHandler(),
    ],
    datefmt='%x %X'
)
logger = logging.getLogger(NAME)
logger.setLevel(logging.DEBUG)

amedastable = {}
with requests.get('https://www.jma.go.jp/bosai/amedas/const/amedastable.json', timeout=10) as r:
    amedastable = r.json()


def deg2dec(deg):
    degree, minute = deg
    return degree + minute / 60


def getNearAmedas(lat, lng):
    if amedastable:
        lines = []
        data = amedastable
        for key in data:
            name = data[key]['kjName']
            elem = data[key]['elems']
            _lat = deg2dec(data[key]['lat'])
            _lng = deg2dec(data[key]['lon'])
            dist = math.dist((lat, lng), (_lat, _lng))
            # snow
            if elem[5] == '1':
                lines.append([key, name, dist])

        return sorted(lines, key=lambda x: x[2])[0]

    return []


def get_interface_name(addr):
    netifs = netif.interfaces()
    for name in netifs:
        nameif = netif.ifaddresses(name)
        for key in nameif:
            ifaddr = nameif[key][0]
            if addr == ifaddr.get('broadcast'):
                return name
    return None


class taskTray:
    def __init__(self):
        self.running = False
        self.config = {}
        self.bulbs = []

        self.readConf(False)

        # 初期アイコン
        self.image = Image.new('RGB', (32, 32), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.app = Icon(name=NAME, title=NAME, icon=self.image)

        self.doTask()

    def buildMenu(self):
        item = [
            MenuItem('Reload', self.readConf),
            Menu.SEPARATOR,
        ]
        for section in self.config:
            item.append(MenuItem(section, self.doOpen, checked=lambda x: self.config[str(x)].get('notified', False)))
        item.append(Menu.SEPARATOR)
        item.append(MenuItem('Exit', self.stopApp))
        return Menu(*item)

    def readConf(self, task=True):
        self.bulbs = []
        self.config = {}
        config = ConfigParser()
        home = os.environ.get('HOME', '.')
        config.read(f'{home}/.config', 'utf-8')
        for section in config.sections():
            self.config[section] = {
                'notified': False,
            }
            for key in config[section]:
                self.config[section][key] = config[section][key]
                if key == 'location':
                    t = config[section][key].split('?')[1].split('&')[:2]
                    for ll in t:
                        k, v = ll.split('=')
                        self.config[section][k] = float(v)
                    code, name, _ = getNearAmedas(self.config[section]['lat'], self.config[section]['lon'])
                    self.config[section]['code'] = code
                elif key == 'bulb':
                    for bulb_ip in self.config[section]['bulb'].split():
                        self.bulbs.append(Bulb(bulb_ip))
                elif key == 'broadcast':
                    interface = get_interface_name(self.config[key]['broadcast'])
                    bulbs = discover_bulbs(interface=interface)
                    for bulb in bulbs:
                        self.bulbs.append(Bulb(bulb['ip']))
            self.config[section]['rgb'] = config[section].get('rgb', '247 246 237')

            if not self.config[section].get('code'):
                del self.config[section]

        if task:
            self.doTask()

    def doTask(self):
        lines = []
        for name in self.config:
            if not self.config[name].get('code'):
                return

            r, g, b = self.getRGB(name, self.config[name])
            rgb = f'{r} {g} {b}'

            # bulbs operation (Yeelight)
            if self.config[name].get('bulb') or self.config[name].get('broadcast'):
                try:
                    if rgb == self.config[name]['rgb'] or (r, g, b) == BLACK:
                        for bulb in self.bulbs:
                            bulb.turn_off()
                        self.draw.rectangle((0, 0, 31, 31), fill=BLACK, outline=WHITE if rgb == self.config[name]['rgb'] else RED)
                    else:
                        self.draw.rectangle((0, 0, 31, 31), fill=(r, g, b), outline=WHITE)
                        for bulb in self.bulbs:
                            bulb.turn_on()
                            bulb.set_rgb(r, g, b)
                            bulb.set_brightness(1)
                except Exception as e:
                    logger.warning(e)

            # bulbs operation (SwitchBot)
            deviceIDs = self.config[name].get('sb_device_id', '').split()
            if deviceIDs:
                try:
                    sb = SwitchBot()
                    if rgb == self.config[name]['rgb'] or (r, g, b) == BLACK:
                        for deviceID in deviceIDs:
                            sb.post_command(deviceID, 'turnOff')
                        self.draw.rectangle((0, 0, 31, 31), fill=BLACK, outline=WHITE if rgb == self.config[name]['rgb'] else RED)
                    else:
                        self.draw.rectangle((0, 0, 31, 31), fill=(r, g, b), outline=WHITE)
                        for deviceID in deviceIDs:
                            sb.post_command(deviceID, 'setBrightness', 1)
                            sb.post_command(deviceID, 'setColor', f'{r}:{g}:{b}')
                            sb.post_command(deviceID, 'turnOn')
                except Exception as e:
                    logger.warning(e)

            # compose notification message with condition
            post_data = {}
            channel = self.config[name].get('channel')
            post_url = self.config[name].get('post')
            notified = self.config[name]['notified']

            if not notified and (self.config[name]['rgb'] != rgb):
                # 通知しておらずデフォルトカラーと異なる (つまり降り始めた)
                line = self.config[name].get('format_falling', 'さんの家、降り始めたみたいです')
                post_data['text'] = name + line
                # 通知済みにする
                self.config[name]['notified'] = True
            elif notified and (self.config[name]['rgb'] == rgb):
                # 通知済みでデフォルトカラーと一致 (つまり止んだ)
                line = self.config[name].get('format_clear', 'さんの家、止んだみたいです')
                post_data['text'] = name + line
                # 通知していない状態に
                self.config[name]['notified'] = False

            if post_data.get('text'):
                if channel:
                    post_data['channel'] = channel
                if post_url:
                    requests.post(post_url, json=post_data, timeout=1)
                if self.config[name].get('vvox', '').lower() == 'on':
                    host = self.config[name].get('vvox_host', 'localhost')
                    port = int(self.config[name].get('vvox_port', 50021))
                    voice = int(self.config[name].get('vvox_voice', 3))
                    speed = float(self.config[name].get('vvox_speed', 1.2))
                    try:
                        vvox(post_data['text'], host=host, port=port, speaker=voice, speed=speed)
                    except Exception as e:
                        logger.warning(e)

                logger.debug(f"{self.config[name]['rgb']} {rgb} {not notified} {post_data}")

            lines.append(f'{name}: {"ok" if self.config[name]['rgb'] == rgb else rgb}')

        self.app.menu = self.buildMenu()
        self.app.title = '\n'.join(lines)
        self.app.icon = self.image
        self.app.update_menu()

    def doOpen(self, _, item):
        name = str(item)
        base = self.config[name]['location'].split('?')
        rainsnow = self.config[name].get('rainsnow', False)
        url = f'{base[0]}{"rainsnow/" if rainsnow else ""}?{base[1]}'
        webbrowser.open(url)

    def stopApp(self):
        self.running = False
        self.app.stop()

    def runSchedule(self):
        schedule.every(INTERVAL).seconds.do(self.doTask)

        while self.running:
            schedule.run_pending()
            time.sleep(1)

    def runApp(self):
        self.running = True

        task_thread = threading.Thread(target=self.runSchedule)
        task_thread.start()

        self.app.run()

    def getRGB(self, name, data):
        # print('getRGB', data)
        code = data['code']
        rainsnow = False
        base = data['location'].split('?')
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))) - dt.timedelta(minutes=10)
        yyyymmdd = now.strftime('%Y%m%d')
        HH = now.strftime('%H')
        hh = f'{int(HH) // 3 * 3:02d}'
        url = f'https://www.jma.go.jp/bosai/amedas/data/point/{code}/{yyyymmdd}_{hh}.json'
        with requests.get(url, timeout=10) as r:
            data = r.json()
            base_key = f'{yyyymmdd}{HH}0000'        # 積雪は1時間毎    pass
            cm, aqc = data[base_key].get('snow', [None, None])
            # 0: 正常 1: 准正常
            if cm is not None and (aqc != 0 or aqc != 1):
                rainsnow = True

        self.config[name]['rainsnow'] = rainsnow
        base_url = f'{base[0]}{"rainsnow/" if rainsnow else ""}?{base[1]}'
        with requests.get(base_url, timeout=10) as r:
            soup = BeautifulSoup(r.content, 'html.parser')
            og_image = soup.find('meta', property='og:image')
            if not og_image:
                return BLACK
            img_url = og_image.get('content').replace('1200x630', '1x1')

            with requests.get(img_url, timeout=10) as r:
                image = Image.open(io.BytesIO(r.content)).convert('RGB')
                return image.getpixel((0, 0))

        return BLACK


if __name__ == '__main__':
    taskTray().runApp()
