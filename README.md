# vox-recorder

Voice activated audio recorder intended for scanner radio use. Record starts when audio level is higher than threshold and records end after 5 seconds of silence.

## Depencies
python3
python3-pyaudio

## Usage

./vox-recorder.py

Audio recordings will be saved to ~/vox-records. Save file type is wav. Audio file names are timestamped eg,

    voxrecord-20180705222631-20180705222639.wav
    
Use another application to select recording soundcard you like to use, like pavucontrol.

## Licence

GPLv3
