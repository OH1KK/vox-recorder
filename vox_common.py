import os
import configparser

CONFIG_FILE_NAME = os.path.join(os.path.dirname(__file__), 'preferences.ini')
MAX_VOLUME = 32767
SAMPLE_CHUNK_SIZE = 1024


def init_config():
  # TODO: This should be shared between the app and config
  config = configparser.ConfigParser()
  config['DEFAULT'] = {
      'SilenceThreshold': 5000,
      'RecordSilenceCutoff': 5,
      'SaveLocation': os.path.join(os.path.expanduser("~"), 'vox-recordings'),
      'SampleRate': 44100,
      'Compress': 'yes',
  }

  if os.path.isfile(CONFIG_FILE_NAME):
    # Load the existing configuration
    config.read(CONFIG_FILE_NAME)
  else:
    # Write a new config file with default values.
    with open('preferences.ini', 'w') as config_file:
      config.write(config_file)
  return config
