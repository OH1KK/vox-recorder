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
from sys import byteorder
from array import array
from struct import pack
import time
import pyaudio
import wave
import os
import sys
import signal
import uuid
import json

# Version of the script
__version__ = "2024.12.15.05"

# Constants
SILENCE_THRESHOLD = 2000
RECORD_AFTER_SILENCE_SECS = 5
WAVEFILES_STORAGEPATH = os.path.expanduser("~/vox-records")
RATE = 44100
MAXIMUMVOL = 32767
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16

class suppress_stdout_stderr(object):
    def __enter__(self):
        self.outnull_file = open(os.devnull, 'w')
        self.errnull_file = open(os.devnull, 'w')

        self.old_stdout_fileno_undup = sys.stdout.fileno()
        self.old_stderr_fileno_undup = sys.stderr.fileno()

        self.old_stdout_fileno = os.dup(sys.stdout.fileno())
        self.old_stderr_fileno = os.dup(sys.stderr.fileno())

        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr

        os.dup2(self.outnull_file.fileno(), self.old_stdout_fileno_undup)
        os.dup2(self.errnull_file.fileno(), self.old_stderr_fileno_undup)

        sys.stdout = self.outnull_file        
        sys.stderr = self.errnull_file
        return self

    def __exit__(self, *_):        
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr

        os.dup2(self.old_stdout_fileno, self.old_stdout_fileno_undup)
        os.dup2(self.old_stderr_fileno, self.old_stderr_fileno_undup)

        os.close(self.old_stdout_fileno)
        os.close(self.old_stderr_fileno)

        self.outnull_file.close()
        self.errnull_file.close()

def signal_handler(signum, frame):
    print("\nProgram interrupted by user. Exiting...")
    sys.exit(0)

def get_metadata():
    """Retrieve metadata from radio or other source. Here, we simulate getting the frequency."""
    # In reality, this would be fetching from your radio or another source
    return {
        "frequency": 145500000,  # Example frequency, replace with actual method to get from radio
        "modulation": 'NFM',  # Example modulation, adjust as needed
        "notes": "Frequency and modulation are incorrect. Radio integration is not implemented."  # User-defined notes
    }

def write_metadata(metadata, filename):
    """Write metadata to a JSON file with the same base name as the audio file."""
    json_filename = f"{filename.rsplit('.', 1)[0]}.json"
    with open(json_filename, 'w') as json_file:
        json.dump(metadata, json_file, indent=4)
    print(f"Metadata saved to: {json_filename}")

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
        indicator = '⏺'
    else:
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
    max_amplitude = max(abs(i) for i in snd_data)
    if max_amplitude == 0:
        return snd_data  # Prevent division by zero
    times = float(MAXIMUMVOL) / max_amplitude
    return array('h', [int(min(MAXIMUMVOL, max(-MAXIMUMVOL, i * times))) for i in snd_data])

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
    with suppress_stdout_stderr():
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
    metadata = get_metadata()
    with suppress_stdout_stderr():
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
                wav_filename = os.path.join(WAVEFILES_STORAGEPATH, f'voxrecord-{time.strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:8]}')
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

    # Save audio with wave module
    with wave.open(f"{wav_filename}.wav", 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(pack('<' + ('h' * len(snd_data)), *snd_data))

    # Update metadata with recording times
    metadata.update({
        "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(record_started_stamp)),
        "end_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
    })
    endtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
    record_time = time.time()-record_started_stamp;
    print(f'\n{endtime} recording finished. Record duraction {record_time:.1f} seconds.')
    write_metadata(metadata, wav_filename)

    return p.get_sample_size(FORMAT), snd_data, f"{wav_filename}.wav"

def voxrecord():
    """Listen audio from the sound card. If audio is detected, record it to file. After recording,
    start again to wait for next activity"""

    # Register the signal handler for SIGINT (Ctrl-C)
    signal.signal(signal.SIGINT, signal_handler)

    while True:
        if not wait_for_activity():
            break  
        try:
            _, _, wav_filename = record_audio()
            print(f'Audio saved to: {wav_filename}')
        except Exception as e:
            print(f"Error during recording: {e}")

if __name__ == '__main__':
    print(f"Voxrecorder v{__version__} started. Hit ctrl-c to quit.")
    
    if not os.access(WAVEFILES_STORAGEPATH, os.W_OK):
        print(f"Wave file save directory {WAVEFILES_STORAGEPATH} does not exist or is not writable. Aborting.")
    else:
        try:
            voxrecord()
        except Exception as e:
            print(f"An unexpected error occurred: {e}")    
    print("Good bye.")

