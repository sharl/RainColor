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

NAME = 'Rain Color'

INTERVAL = 5 * 60
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
D_TEMP = 100
D_SNOW = -1
WD = '静穏 北北東 北東 東北東 東 東南東 南東 南南東 南 南南西 南西 西南西 西 西北西 北西 北北西 北'.split()
WEATHER_INFO = {
    0: "晴",
    1: "曇",
    2: "煙霧",
    3: "霧",
    4: "降水またはしゅう雨性の降水",
    5: "霧雨",
    6: "着氷性の霧雨",
    7: "雨",
    8: "着氷性の雨",
    9: "みぞれ",
    10: "雪",
    11: "凍雨",
    12: "霧雪",
    13: "しゅう雨または止み間のある雨",
    14: "しゅう雪または止み間のある雪",
    15: "ひょう",
    16: "雷",
    30: "天気不明",
    31: "欠測",
}

# AQC (Automatic Quality Control) 識別符号
# https://www.data.jma.go.jp/stats/data/mdrr/man/remark.html
# https://www.data.jma.go.jp/suishin/shiyou/pdf/no13301
# 0 正常
# 1 準正常 (やや疑わしい)
# 2 非常に疑わしい
# 3 利用に適さない
# 4 観測値は期間内で資料数が不足している
# 5 点検又は計画休止のため欠測
# 6 障害のため欠測
# 7 この要素の観測はしていない
AQC_INFO = {
    0: '',
    1: ')',
    2: '#',
    3: '#',
    4: ']',
    5: '休止中',
    6: '✕',
    None: '　',
}
ずんだもん = [3, 22]
四国めたん = [2, 36]

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
    datefmt='%Y/%m/%d %X'
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

        # 最初に定義された amedas code
        self.default = None
        self.readConf(False)

        # 初期アイコン
        self.image = Image.new('RGB', (32, 32), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.app = Icon(name=NAME, title=NAME, icon=self.image)

        self.doTask()

    def buildMenu(self):
        item = [
            MenuItem('do it', self.doIt, visible=False, default=True),
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
                    if not self.default:
                        self.default = code
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

            r, g, b = self.getRGB(name)
            lines += self.config[name].get('lines', [])
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

            if self.config[name]['rgb'] != rgb:
                lines.append(rgb)

        self.app.menu = self.buildMenu()
        self.app.title = '\n'.join(lines)
        self.app.icon = self.image
        self.app.update_menu()

    def _openURL(self, name: str):
        base = self.config[name]['location'].split('?')
        rainsnow = self.config[name].get('rainsnow', False)
        url = f'{base[0]}{"rainsnow/" if rainsnow else ""}?{base[1]}'
        webbrowser.open(url)

    def doIt(self):
        if len(self.config) == 1:
            name = list(self.config)[0]
            self._openURL(name)

    def doOpen(self, _, item):
        name = str(item)
        self._openURL(name)

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

    def daytime(self, speaker):
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
        if now.hour <= 5:
            return speaker[1]
        return speaker[0]

    def vvox_temp(self, name):
        if self.config[name].get('vvox').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{name}が'
        temp = self.config[name].get('temp')
        pm = ''
        if temp < 0:
            temp = -temp
            pm = 'マイナス'
        vvox(f"{_name}{pm}{str(temp).replace('.0', '')}度になったのだ", speaker=self.daytime(ずんだもん))

    def vvox_snow(self, name, plus):
        if self.config[name].get('vvox').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{name}が'
        _plus = '増えた' if plus else 'なった'
        vvox(f'{_name}{self.snow}センチに{_plus}わ', speaker=self.daytime(四国めたん))

    def vvox_weather(self, name):
        if self.config[name].get('vvox').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{self.name}は'
        vvox(f'{_name}{self.config[name].get('weather', '不明')}なのだ', speaker=self.daytime(ずんだもん))

    def getRGB(self, name):
        # print('getRGB', self.config[name])
        code = self.config[name]['code']
        rainsnow = False
        base = self.config[name]['location'].split('?')
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))) - dt.timedelta(minutes=10)
        yyyymmdd = now.strftime('%Y%m%d')
        HH = now.strftime('%H')
        hh = f'{int(HH) // 3 * 3:02d}'
        url = f'https://www.jma.go.jp/bosai/amedas/data/point/{code}/{yyyymmdd}_{hh}.json'
        try:
            with requests.get(url, timeout=10) as r:
                data = r.json()
                base_key = f'{yyyymmdd}{HH}0000'        # 積雪は1時間毎    pass
                last_key = list(data.keys())[-1]
                _vars = data[base_key]
                for k in data[last_key]:
                    _vars[k] = data[last_key][k]
                cm, aqc = data[base_key].get('snow', [None, None])
                # 0: 正常 1: 准正常
                if cm is not None and (aqc != 0 or aqc != 1):
                    rainsnow = True
                h = last_key[8:10]
                if h == '00':
                    h = '24'
                m = last_key[10:12]
                lines = [
                    f'{name} {h}:{m}',
                ]
                weather = None
                temp = D_TEMP
                snow = D_SNOW
                for x in [
                        '天気 weather -',
                        '気温 temp 度',
                        '降水 precipitation1h mm/h',
                        '風向 windDirection -',
                        '風速 wind m/s',
                        '積雪 snow cm',
                        '降雪 snow1h cm/h',
                        '湿度 humidity %',
                        '気圧 pressure hPa',
                ]:
                    t, k, u = x.split()
                    if k in _vars:
                        v, aqc = _vars[k]
                        # print(k, [v, aqc])
                        # 0: 正常 1: 准正常
                        if aqc != 0 and aqc != 1:
                            continue

                        if isinstance(v, float):
                            if v == int(v):
                                v = int(v)

                        if k == 'weather':
                            weather = WEATHER_INFO[v]
                            if weather != self.config[name].get('weather'):
                                self.config[name]['weather'] = weather
                                self.vvox_weather(name)
                        elif k == 'temp':
                            temp = v
                            if int(temp) != int(self.config[name].get('temp', D_TEMP)):
                                self.config[name]['temp'] = temp
                                self.vvox_temp(name)
                        elif k == 'snow':
                            snow = v
                            if snow is not None and snow != self.config[name].get('snow'):
                                plus = snow > self.config[name].get('snow') and self.config[name].get('snow') != D_SNOW
                                self.config[name]['snow'] = snow
                                self.vvox_snow(name, plus)

                        if k == 'windDirection':
                            lines.append(f'{t} {WD[v]}')
                        elif k == 'weather':
                            lines.append(f'{t} {WEATHER_INFO[v]}')
                        else:
                            lines.append(f'{t} {v}{u}')
                self.config[name]['lines'] = lines
        except Exception as e:
            logger.warning(e)
        finally:
            pass

        self.config[name]['rainsnow'] = rainsnow
        base_url = f'{base[0]}{"rainsnow/" if rainsnow else ""}?{base[1]}'
        try:
            with requests.get(base_url, timeout=10) as r:
                soup = BeautifulSoup(r.content, 'html.parser')
                og_image = soup.find('meta', property='og:image')
                if not og_image:
                    return BLACK
                img_url = og_image.get('content').replace('1200x630', '1x1')

                with requests.get(img_url, timeout=10) as r:
                    try:
                        image = Image.open(io.BytesIO(r.content)).convert('RGB')
                    except Exception as e:
                        print('Exception', e)
                        return BLACK
                    return image.getpixel((0, 0))
        except Exception as e:
            logger.warning(e)

        return BLACK


if __name__ == '__main__':
    taskTray().runApp()
