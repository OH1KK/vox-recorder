#!/usr/bin/env python3
"""
   VOX-recorder records audio when there is sound present
   Copyright (C) 2015  Kari Karvonen <oh1kk at toimii.fi>

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software Foundation,
   Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
                                       
"""
from __future__ import print_function
from sys import byteorder
from array import array
from struct import pack

import time
import pyaudio
import wave
import os

SILENCE_THRESHOLD = 5000
RECORD_AFTER_SILENCE_SECS = 5
WAVEFILES_STORAGEPATH = os.path.expanduser("~/vox-records");

RATE = 44100
MAXIMUMVOL = 32767
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16

def show_status(snd_data, record_started, record_started_stamp, wav_filename):
    "Displays volume levels"
    
    if voice_detected(snd_data):
        status = "Voice"
    else:
        status = "Silence"
    
    print ('Volume: %d/%d. %s, threshold %d. ' % (max(snd_data), MAXIMUMVOL, status, SILENCE_THRESHOLD), end='')
    if record_started:
        elapsed = time.time() - record_started_stamp;
        print ('Recording to file %s-xxxxxxxxxxxxxx.wav (%d seconds recorded)         ' % (wav_filename, elapsed), end='\r')
    else:
        print ('                                                                   ', end='\r')

def voice_detected(snd_data):
    "Returns 'True' if sound peaked above the 'silent' threshold"
    return max(snd_data) > SILENCE_THRESHOLD

def normalize(snd_data):
    "Average the volume out"
    times = float(MAXIMUMVOL)/max(abs(i) for i in snd_data)

    r = array('h')
    for i in snd_data:
        r.append(int(i*times))
    return r

def trim(snd_data):
    "Trim the blank spots at the start and end"
    def _trim(snd_data):
        record_started = False
        r = array('h')

        for i in snd_data:
            if not record_started and abs(i)>SILENCE_THRESHOLD:
                record_started = True
                r.append(i)

            elif record_started:
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
    "Add silence to the start and end of 'snd_data' of length 'seconds' (float)"
    r = array('h', [0 for i in range(int(seconds*RATE))])
    r.extend(snd_data)
    r.extend([0 for i in range(int(seconds*RATE))])
    return r

def wait_for_activity():
    """
    Listen sound and quit when sound is detected 
    """
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=RATE,
        input=True, output=True,
        frames_per_buffer=CHUNK_SIZE)

    record_started_stamp = 0
    wav_filename = ''
    record_started = False

    while 1:
        # little endian, signed short
        snd_data = array('h', stream.read(CHUNK_SIZE))
        if byteorder == 'big':
            snd_data.byteswap()

        voice = voice_detected(snd_data)
        show_status(snd_data, record_started, record_started_stamp, wav_filename)
        del snd_data

        if voice:
            break
        
    stream.stop_stream()
    stream.close()
    p.terminate()
    return True


def record_audio():
    """
    Record audio when activity is detected 

    Normalizes the audio, trims silence from the 
    start and end, and pads with 0.5 seconds of 
    blank sound to make sure VLC et al can play 
    it without getting chopped off.
    """
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=1, rate=RATE,
        input=True, output=True,
        frames_per_buffer=CHUNK_SIZE)

    num_silent = 0
    record_started_stamp = 0
    last_voice_stamp = 0
    wav_filename = ''
    record_started = False

    r = array('h')

    while 1:
        # little endian, signed short
        snd_data = array('h', stream.read(CHUNK_SIZE))
        if byteorder == 'big':
            snd_data.byteswap()
        r.extend(snd_data)

        voice = voice_detected(snd_data)
        show_status(snd_data, record_started, record_started_stamp, wav_filename)

        if voice and record_started:
            last_voice_stamp = time.time();
        elif voice and not record_started:
            record_started = True
            record_started_stamp = last_voice_stamp = time.time();
            datetime = time.strftime("%Y%m%d%H%M%S")
            wav_filename = '%s/voxrecord-%s' % (WAVEFILES_STORAGEPATH,datetime)
        
        if record_started and time.time() > (last_voice_stamp + RECORD_AFTER_SILENCE_SECS):
            break

    sample_width = p.get_sample_size(FORMAT)
    stream.stop_stream()
    stream.close()
    p.terminate()

    datetime = time.strftime("%Y%m%d%H%M%S")
    wav_filename += '-%s.wav' % datetime

    r = normalize(r)
    r = trim(r)
    r = add_silence(r, 0.5)
    return sample_width, r, wav_filename

def voxrecord():
    """
    Listen audio from soudcard. If audio is detected, record it to file. After recording,
    start again to wait for next activity
    """
            
    while 1:
        idle = wait_for_activity()
        sample_width, data, wav_filename = record_audio()
        data = pack('<' + ('h'*len(data)), *data)
        wf = wave.open(wav_filename, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(sample_width)
        wf.setframerate(RATE)
        wf.writeframes(data)
        wf.close()
        print()
        recinfo = 'Recording finished. Saved to: %s' % (wav_filename)
        print(recinfo)


if __name__ == '__main__':
    print("Voxrecorder started. Hit ctrl-c to quit.")
      
    if not os.access(WAVEFILES_STORAGEPATH, os.W_OK):
        print("Wave file save directory %s does not exist or is not writable. Aborting." % WAVEFILES_STORAGEPATH)
    else:
        voxrecord()
    
    print("Good bye.")
