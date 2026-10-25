# -*- coding: utf-8 -*-
import io
import struct
import sys
import wave

from pvspeaker import PvSpeaker
import requests


def vvox(text, host='127.0.0.1', port=50021, speaker=3, speed=1.0, volume=1.0, stdout=False):
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

    if stdout:
        sys.stdout.buffer.write(synthesis.content)
        sys.stdout.buffer.flush()
    else:
        with wave.open(io.BytesIO(synthesis.content), 'rb') as wf:
            sample_rate = wf.getframerate()
            sample_width = wf.getsampwidth()
            bits_per_sample = sample_width * 8

            # unpack to picovoice array
            raw_bytes = wf.readframes(wf.getnframes())
            num_samples = len(raw_bytes) // sample_width
            pcm_data = struct.unpack(f"{num_samples}h", raw_bytes)

            speaker = PvSpeaker(
                sample_rate=sample_rate,
                bits_per_sample=bits_per_sample,
            )
            speaker.start()
            speaker.write(pcm_data)
            speaker.flush()
            speaker.stop()
            speaker.delete()
