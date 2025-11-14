# RainColor

Yahoo 雨雲レーダー画像を取得して降水量の色をタスクトレイアイコンに反映

## About

複数地点が指定可能です

オプションとして

- 降水量の色を Yeelight の RGB デバイスに反映
- 降水量の色を SwitchBot の RGB デバイスに反映
- VOICEVOX でお知らせ
- Slack の incoming hook gateway にメッセージを送信

を地点ごとに設定可能です

## Run

```
git clone https://github.com/sharl/RainColor.git
cd RainColor
pip install -r requirements.txt
python Yeelight-RainColor.py
```

## .config 書式

```
[sample]
location = https://weather.yahoo.co.jp/weather/zoomradar/?lat=42.923&lon=143.193&z=12
rgb = 241 241 239
# bulb = 192.168.0.204 192.168.0.220
# broadcast = 192.168.0.255
# sb_device_id = XXXXXXXXXXXX YYYYYYYYYYYY
# vvox = off
# vvox_host = localhost
# vvox_port = 50021
# vvox_voice = 3
# vvox_speed = 1.2
# format_falling = さんの家、降り始めたみたいです
# format_clear   = さんの家、止んだみたいです
# channel = dev
# post = http://localhost:16543/chat_postMessage
```

### [sample]

`sample` が地点名です

例
```
[帯広]
```

### location

緯度・経度・拡大率が含まれている [雨雲レーダー](https://weather.yahoo.co.jp/weather/zoomradar/) の URL

『URLを表示』でパーマリンクが表示されるのでその内容を設定してください

### rgb

雨が降っていないときの観測地点の色

デフォルトは 247 246 237

この色と異なる場合にタスクトレイアイコンに反映されます

### bulb

Yeelight RGB デバイスの IP アドレス 空白区切りで複数指定可能

### broadcast

対象ネットワークのすべての Yeelight RGB デバイスを使用

### sb_device_id

SwichBot RGB デバイスの ID です 空白区切りで複数指定可能

### vvox

VOICEVOX で通知する場合 on を指定します

以下はオプションとデフォルトです

- vvox_host = localhost
- vvox_port = 50021
- vvox_voice = 3
- vvox_speed = 1.2
- format_falling = さんの家、降り始めたみたいです
- format_clear   = さんの家、止んだみたいです

必要に応じて変更してください

### channel, post (実験的機能)

Slack の incoming hook gateway にメッセージを送信します
