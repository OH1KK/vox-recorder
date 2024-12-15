#!/usr/bin/env python3
"""
VOX-recorder records audio when there is sound present
Copyright (C) 2015-2024 Kari Karvonen <oh1kk@toimii.fi>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software Foundation,
Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
"""

from __future__ import print_function
from sys import byteorder
from array import array
from struct import pack
import time
import pyaudio
import wave
import os

# Version of the script
__version__ = "2024.12.15.02"

# Constants
SILENCE_THRESHOLD = 2000
RECORD_AFTER_SILENCE_SECS = 5
WAVEFILES_STORAGEPATH = os.path.expanduser("~/vox-records")
RATE = 44100
MAXIMUMVOL = 32767
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16

import time

def show_status(snd_data, record_started, record_started_stamp, wav_filename):
    """Displays volume levels with a VU-meter bar, threshold marker, and indicator for audio presence or recording"""
    voice = voice_detected(snd_data)
    status = "Audio Detected - Recording to file" if record_started else "Waiting for audio to exceed threshold"
    
    # Calculate simple VU level for visual feedback
    vu_level = min(int((max(snd_data) / MAXIMUMVOL) * 30), 30)
    vu_bar = "█" * vu_level + " " * (30 - vu_level)
    
    # Add a marker for the threshold
    threshold_position = min(int((SILENCE_THRESHOLD / MAXIMUMVOL) * 30), 30)
    vu_bar = vu_bar[:threshold_position] + '|' + vu_bar[threshold_position + 1:]
    
    # Audio presence or recording indicator
    if record_started:
        # Always show '⏺' when recording
        indicator = '⏺'
    else:
        # Blinking '⏸' for audio presence when not recording
        cycle = int(time.time() * 2) % 2  # Blink every 0.5 seconds
        indicator = '⏸' if cycle and any(abs(x) > 0 for x in snd_data) else ' '

    # Print the VU meter with threshold marker, status, and indicator
    print(f'\rVU: [{vu_bar}] | {indicator} {status}', end='')
    if record_started:
        elapsed = time.time() - record_started_stamp
        print(f' | File: {os.path.basename(wav_filename)} | Time: {elapsed:.1f}s', end='')
    else:
        print('                                                  ', end='')  # Clear previous status
    
    # Move cursor to the beginning of the line for next update
    print('\r', end='')

def voice_detected(snd_data):
    """Returns 'True' if sound peaked above the 'silent' threshold"""
    return max(snd_data) > SILENCE_THRESHOLD

def normalize(snd_data):
    """Average the volume out"""
    times = float(MAXIMUMVOL) / max(abs(i) for i in snd_data)
    return array('h', [int(i * times) for i in snd_data])

def trim(snd_data):
    """Trim the blank spots at the start and end"""
    def _trim(snd_data):
        record_started = False
        r = array('h')
        for i in snd_data:
            if not record_started and abs(i) > SILENCE_THRESHOLD:
                record_started = True
            if record_started:
                r.append(i)
        return r

    # Trim to the left
    snd_data = _trim(snd_data)
    # Trim to the right
    snd_data.reverse()
    snd_data = _trim(snd_data)
    snd_data.reverse()
    return snd_data

def add_silence(snd_data, seconds):
    """Add silence to the start and end of 'snd_data' of length 'seconds' (float)"""
    silence = array('h', [0 for _ in range(int(seconds * RATE))])
    return silence + snd_data + silence

def wait_for_activity():
    """Listen sound and quit when sound is detected"""
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK_SIZE)
    
    try:
        while True:
            snd_data = array('h', stream.read(CHUNK_SIZE))
            if byteorder == 'big':
                snd_data.byteswap()
            voice = voice_detected(snd_data)
            show_status(snd_data, False, 0, '')
            if voice:
                break
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
    return True

def record_audio():
    """Record audio when activity is detected"""
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=RATE, input=True, frames_per_buffer=CHUNK_SIZE)
    snd_data = array('h')
    record_started = False
    last_voice_stamp = 0
    record_started_stamp = 0
    wav_filename = ''

    try:
        while True:
            chunk = array('h', stream.read(CHUNK_SIZE))
            if byteorder == 'big':
                chunk.byteswap()
            snd_data.extend(chunk)
            
            voice = voice_detected(chunk)
            show_status(chunk, record_started, record_started_stamp, wav_filename)

            if voice and not record_started:
                record_started = True
                record_started_stamp = last_voice_stamp = time.time()
                wav_filename = os.path.join(WAVEFILES_STORAGEPATH, f'voxrecord-{time.strftime("%Y%m%d%H%M%S")}')
            elif voice and record_started:
                last_voice_stamp = time.time()
            
            if record_started and time.time() > last_voice_stamp + RECORD_AFTER_SILENCE_SECS:
                break
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    # Process audio
    snd_data = normalize(snd_data)
    snd_data = trim(snd_data)
    snd_data = add_silence(snd_data, 0.5)
    return p.get_sample_size(FORMAT), snd_data, f'{wav_filename}-{time.strftime("%Y%m%d%H%M%S")}.wav'

def voxrecord():
    """Listen audio from the sound card. If audio is detected, record it to file. After recording,
    start again to wait for next activity"""
    while True:
        wait_for_activity()
        sample_width, data, wav_filename = record_audio()
        with wave.open(wav_filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(sample_width)
            wf.setframerate(RATE)
            wf.writeframes(pack('<' + ('h' * len(data)), *data))
        print(f'\nRecording finished. Saved to: {wav_filename}')

if __name__ == '__main__':
    print(f"Voxrecorder v{__version__} started. Hit ctrl-c to quit.")
    
    if not os.access(WAVEFILES_STORAGEPATH, os.W_OK):
        print(f"Wave file save directory {WAVEFILES_STORAGEPATH} does not exist or is not writable. Aborting.")
    else:
        voxrecord()
    
    print("Good bye.")
