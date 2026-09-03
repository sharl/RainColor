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
import webbrowser

from PIL import Image, ImageDraw, ImageFont
from SwitchBot import SwitchBot
from bs4 import BeautifulSoup
from pystray import Icon, Menu, MenuItem
from vvox import vvox
from yeelight import discover_bulbs, Bulb
import darkdetect as dd
import netifaces as netif
import requests
import schedule

from Badges import Badges
from utils import resource_path, getLog

NAME = 'RainColor'

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
AQC_OK = [0, 1]
ずんだもん = [3, 22]
四国めたん = [2, 36]

PreferredAppMode = {
    'Light': 0,
    'Dark': 1,
}
# https://github.com/moses-palmer/pystray/issues/130
ctypes.windll['uxtheme.dll'][135](PreferredAppMode[dd.theme()])


# logger settings
logname = getLog(NAME, 'log.log')
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(logname, encoding='utf-8', maxBytes=1000000, backupCount=0),
        logging.StreamHandler(),
    ],
    datefmt='%Y/%m/%d %X'
)
logger = logging.getLogger(NAME)
logger.setLevel(logging.DEBUG)


def deg2dec(deg):
    degree, minute = deg
    return degree + minute / 60


def getNearAmedas(lat, lng, amedastable={}):
    if not amedastable:
        AMEDASTABLE_URL = 'https://www.jma.go.jp/bosai/amedas/const/amedastable.json'
        with requests.get(AMEDASTABLE_URL, timeout=10) as r:
            amedastable.update(r.json())

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
        self.stop_event = threading.Event()
        self.config = {}
        self.show_badges = True
        self.bulbs = []

        # 最初に定義された amedas code
        self.default = None
        self.readConf(False)

        # 初期アイコン
        self.image = Image.new('RGB', (32, 32), WHITE)
        self.draw = ImageDraw.Draw(self.image)
        self.app = Icon(name=NAME, title=NAME, icon=self.image)
        self.badges = Badges()
        self.badges.start()

        self.doTask()

    def buildMenu(self):
        item = [
            MenuItem('do it', self.doIt, visible=False, default=True),
            MenuItem('Show Badge', self.toggleBadges, checked=lambda _: self.show_badges),
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

    def getImages(self, w, t, s):
        def create_fitted_text_image(text, font_path=r"C:\Windows\Fonts\arialbd.ttf", target_height=72, padding=16):
            # 1. 適切なフォントサイズを推測（高さ72pxなら、フォントサイズもだいたい72から開始）
            font_size = target_height
            font = ImageFont.truetype(font_path, font_size)

            # 2. textbbox で実際の描画サイズを測定
            # (left, top, right, bottom) が返る
            bbox = ImageDraw.Draw(Image.new("RGB", (0, 0))).textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # 3. 高さに合わせてフォントサイズを微調整（比率計算）
            # 実際の高さ text_h が target_height になるようにスケールさせる
            adjusted_font_size = int(font_size * (target_height / text_h)) - padding
            font = ImageFont.truetype(font_path, adjusted_font_size)

            # 再測定
            bbox = ImageDraw.Draw(Image.new("RGB", (0, 0))).textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # 4. 画像の作成（横幅は文字に合わせて可変）
            img_w = text_w + (padding * 2)
            img_h = target_height + (padding * 2)
            image = Image.new("RGB", (int(img_w), int(img_h)), (0, 0, 0))
            draw = ImageDraw.Draw(image)

            # 5. 描画位置の計算
            # textbbox の left, top を引くことで、余白をリセットして左上に詰められます
            draw.text((padding - bbox[0], padding * 2 - bbox[1]), text, font=font, fill=(255, 255, 255))

            return image

        images = []
        # 天気アイコン
        icons = {
            "晴": '2600',
            "曇": '2601',
            "霧": '1f32b',
            "雨": '2614',
            "みぞれ": '1f367',
            "雪": '2603',
            "雷": '26a1',
        }
        if w in icons:
            code_point = icons[w]
            image = Image.open(resource_path(f'Assets/emoji_u{code_point}.png'))
            images.append(image)
        elif w is None:
            pass
        else:
            print(f'{w} not in icons')
            vvox(f'想定外の天気アイコンが発生しました {w}', speed=1.2)

        # 気温
        if t != D_TEMP:
            image = create_fitted_text_image(f'{t}C')
            images.append(image)

        # 積雪
        if s is not None and s != D_SNOW and s != 0:
            image = create_fitted_text_image(f'{s}cm')
            images.append(image)

        return images

    def daytime(self, speaker):
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
        if now.hour <= 5:
            return speaker[1]
        return speaker[0]

    def vvox_temp(self, name):
        if self.config[name].get('vvox', '').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{name}が'
        temp = self.config[name].get('temp')
        pm = ''
        if temp < 0:
            temp = -temp
            pm = 'マイナス'
        vvox(f"{_name}{pm}{str(temp).replace('.0', '')}度になったのだ", speaker=self.daytime(ずんだもん))

    def vvox_snow(self, name, plus):
        if self.config[name].get('vvox', '').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{name}が'
        snow = self.config[name].get('snow')
        _plus = '増えた' if plus else 'なった'
        vvox(f'{_name}{snow}センチに{_plus}わ', speaker=self.daytime(四国めたん))

    def vvox_weather(self, name):
        if self.config[name].get('vvox', '').lower() != 'on':
            return

        _name = '' if self.config[name].get('code') == self.default else f'{self.name}は'
        weather = self.config[name].get('weather')
        vvox(f'{_name}{weather}なのだ', speaker=self.daytime(ずんだもん))

    def amedas(self, name: str):
        """
        sat values
        - self.config[name]
          - rainsnow: bool
          - weather: str
          - temp: float
          - snow: int
          - lines: list[str]
        """
        code = self.config[name].get('code')
        now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))) - dt.timedelta(minutes=10)
        yyyymmdd = now.strftime('%Y%m%d')
        HH = now.strftime('%H')
        hh = f'{int(HH) // 3 * 3:02d}'
        url = f'https://www.jma.go.jp/bosai/amedas/data/point/{code}/{yyyymmdd}_{hh}.json'
        try:
            with requests.get(url, timeout=10) as r:
                rainsnow = False
                weather = None
                temp = D_TEMP
                snow = D_SNOW

                # set newest data to _vars
                data = r.json()
                base_key = f'{yyyymmdd}{HH}0000'        # 積雪は1時間毎
                last_key = list(data.keys())[-1]
                _vars = data[base_key]
                for k in data[last_key]:
                    _vars[k] = data[last_key][k]

                # detect rainsnow
                cm, aqc = data[base_key].get('snow', [None, None])
                # 0: 正常 1: 准正常
                if cm is not None and aqc in AQC_OK:
                    rainsnow = True
                self.config[name]['rainsnow'] = rainsnow

                h = last_key[8:10]
                if h == '00':
                    h = '24'
                m = last_key[10:12]
                lines = [
                    f'{name} {h}:{m}',
                ]
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
                        if aqc not in AQC_OK:
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
        finally:
            return rainsnow, weather, temp, snow

    def yeelight(self, name: str, r: int, g: int, b: int):
        """
        bulbs operation (Yeelight)
        """
        rgb = f'{r} {g} {b}'

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

    def switchbot(self, name: str, r: int, g: int, b: int):
        """
        bulbs operation (SwitchBot)
        """
        rgb = f'{r} {g} {b}'

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

    def voicevox(self, name: str, r: int, g: int, b: int):
        """
        experimental: post channel

        voicevox operation
        """
        rgb = f'{r} {g} {b}'

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

    def getRGB(self, name: str) -> list[int]:
        rainsnow = self.config[name].get('rainsnow', False)
        base = self.config[name]['location'].split('?')
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
                        logger.debug(f'Exception: map image {e}')
                        return BLACK
                    return image.getpixel((0, 0))
        except Exception as e:
            logger.warning(e)

        return BLACK

    def doTask(self):
        lines = []
        for name in self.config:
            if not self.config[name].get('code'):
                return

            # get amedas
            rainsnow, weather, temp, snow = self.amedas(name)

            # get RGB
            r, g, b = self.getRGB(name)
            rgb = f'{r} {g} {b}'

            if self.config[name].get('code') == self.default:
                # set Yeelight
                self.yeelight(name, r, g, b)
                # set Switchbot
                self.switchbot(name, r, g, b)

                # update badge
                # self.badges[name].updateBadge()
                images = self.getImages(weather, temp, snow)
                self.badges.set_visible(self.show_badges)
                self.badges.update(images)

            # post and voicevox
            self.voicevox(name, r, g, b)

            lines += self.config[name].get('lines', [])
            if self.config[name]['rgb'] != rgb:
                lines.append(rgb)

            print(rainsnow, weather, temp, snow, rgb)

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

    def toggleBadges(self, _, __):
        self.show_badges = not self.show_badges
        self.badges.set_visible(self.show_badges)

    def stopApp(self):
        self.stop_event.set()
        self.app.stop()

    def runSchedule(self):
        schedule.every(INTERVAL).seconds.do(self.doTask)

        while not self.stop_event.is_set():
            schedule.run_pending()
            if self.stop_event.wait(1):
                break

    def runApp(self):
        self.stop_event.clear()
        threading.Thread(target=self.runSchedule).start()
        self.app.run()


if __name__ == '__main__':
    taskTray().runApp()
