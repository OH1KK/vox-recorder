# vox-recorder
VOX Recorder is a simple voice-activated audio recorder. It is used primarily for scanner radio use. Recording starts when the audio level is above a configured threshold and ends after a period of silence.

This repository is to be an enhancement of the existing vox-recorder project.

It allows configuration of options using an ini-like file.

**TODO: Create issues to track these features.**

It will feature a gui that allows the user to set and preview their configuration before starting the application.

There will be the ability to compress captured audio (libopus probably).

I am exploring the possibility of being able to select an input device. This is a low priority.


## Requirements
**TODO: Generate requirements.txt to replace this section**
- PyAudio 0.2.11

## Usage

./vox-recorder.py

Audio recordings will be saved to `~/vox-records` by default. This option can be configured in `preferences.ini`. Files are saved as uncompressed WAV at CD quality (44.1 kHz). Output file names are timestamped e.g.
```
    voxrecord-20180705222631-20180705222639.wav
```

Currently it isn't possible to select a recording device other than the system default.
Your operating system or other applications may be able to do this. pavucontrol is provided as an option for gnu/linux systems

## Licence

GPLv3
