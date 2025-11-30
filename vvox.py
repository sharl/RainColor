# -*- coding: utf-8 -*-
import io
import wave

import pyaudio
import requests


def vvox(text, host='127.0.0.1', port=50021, speaker=3, speed=1.0, volume=1.0):
    params = {
        'text': text,
        'speaker': speaker,
    }
    query = requests.post(
        f'http://{host}:{port}/audio_query',
        params=params,
        timeout=10,
    )
    qp = query.json()
    # modify query
    qp['speedScale'] = speed
    qp['volumeScale'] = volume

    synthesis = requests.post(
        f'http://{host}:{port}/synthesis',
        params=params,
        json=qp,
        timeout=10,
    )

    with wave.open(io.BytesIO(synthesis.content), 'rb') as wf:
        data = wf.readframes(wf.getnframes())

        pya = pyaudio.PyAudio()
        stream = pya.open(
            format=pya.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True,
        )
        stream.write(data)
        stream.stop_stream()
        stream.close()
        pya.terminate()
