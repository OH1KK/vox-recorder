# Vox-Recorder

**Vox-Recorder** is a voice-activated audio recorder designed primarily for use with scanner radios. It automatically starts recording when the audio level exceeds a predefined threshold and stops recording after 5 seconds of silence.

## Dependencies

- **Python 3**
- **PyAudio** (install with `sudo apt install python3-pyaudio`)

## Installation

Clone the Repository

```bash
apt install git
git clone https://github.com/OH1KK/vox-recorder.git
``` 
## Usage

To run the recorder:
```
cd vox-recorder
python3 ./vox-recorder.py
```

## Output

- Audio Recordings: Saved to ~/vox-records/
- Audio file format: WAV
- Metadata file format: json
- File Naming: Files are named with timestamps indicating the start time of recording following unique id

For example:

```
voxrecord-20241215175916-ad63d362.wav
voxrecord-20241215175916-ad63d362.json
```

## Configuration

- Select Input Device: Use your preferred sound mixer application to choose the correct recording device. We recommend pavucontrol for Linux users.
- Adjust Recording Volume: Ensure the volume is set appropriately to capture the desired audio levels.

## Features

- Automatic Start/Stop: Recording begins when audio surpasses the silence threshold and ends after 5 seconds of silence.
- Save metadata file that includes recording start and end times.
- Real-time Feedback: Includes a VU-meter display for monitoring audio levels in real-time.

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
