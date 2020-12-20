import os
import configparser

CONFIG_FILE_NAME = os.path.join(os.path.dirname(__file__), 'preferences.ini')
MAX_VOLUME = 32767
SAMPLE_CHUNK_SIZE = 1024


def bool_to_str(boolval):
  return 'yes' if boolval else 'no'


def init_config():
  """Loads the default configuration and writes it to a file, or if a config
  file is already present, loads the parameters from it.
  """

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
    with open(CONFIG_FILE_NAME, 'w') as config_file:
      config.write(config_file)
  return config
