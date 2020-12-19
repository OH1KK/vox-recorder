from __future__ import print_function
from sys import byteorder
from array import array
from struct import pack

import time
import pyaudio
import wave
import os
import threading

from tkinter import *
from tkinter import ttk

import queue

import configparser

CONFIG_FILE_NAME = os.path.join(os.path.dirname(__file__), 'preferences.ini')
LAYOUT_PADDING = "3 3 12 12"

#TODO: Remove max volume option. It's just max 16 bit integer.

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
    config.read(CONFIG_FILE_NAME)
  else:
    with open('preferences.ini', 'w') as config_file:
      config.write(config_file)
  return config


class Counter:
  """A simple counter that increments every time you call it (starts at 1)
  """

  def __init__(self):
    super().__init__()
    self.__i = 0

  def next(self):
    """Increments the counter and returns the next value.
    """
    self.__i += 1
    return self.__i;


class MainWindow(object):
  """Represents the main window of a configuration dialog. This dialog is used
  to configure the script options of the vox-recorder program, as well as testing
  microphone settings.
  :param parent: The root TK object that is managing the event loop.
  :type parent: TK
  """

  def __init__(self, parent):
    super().__init__()
    if not isinstance(parent, Tk):
      raise AttributeError("Parent must be an instance of TK")
    self._parent = parent
    self._parent.protocol("WM_DELETE_WINDOW", self._do_on_window_closing)

    self._parent.title("Vox Settings")
    self._parent.columnconfigure(0, weight=1)
    self._parent.rowconfigure(0, weight=1)
    self._parent.wm_minsize(529, 437)
    self._parent.bind

    self._monitor_queue = queue.LifoQueue()

    self._pref_form_row_counter = Counter()

    self._c_silence_threshold = IntVar()
    self._c_silence_cutoff = IntVar()
    self._c_save_location = StringVar()
    self._c_sample_rate = IntVar()
    self._c_compress = BooleanVar()

    self._reload_config()

    #region form definition
    mainframe = ttk.Frame(root, padding=LAYOUT_PADDING)
    mainframe.grid(column=0, row=0, sticky=(N, W, E, S))
    mainframe.columnconfigure(0, weight=1)
    mainframe.rowconfigure(0, weight=1 )
    self._preference_frame = ttk.Frame(mainframe, padding=LAYOUT_PADDING, borderwidth=5, relief="ridge")
    self._preference_frame.grid(column=0, row=0, sticky=(N, W, E, S))
    self._preference_frame.columnconfigure(1, weight=1)
    self._dialog_button_frame = ttk.Frame(mainframe, padding=LAYOUT_PADDING)


    row = self._pref_form_row_counter.next()
    ttk.Label(self._preference_frame, text="Recording Threshold").grid(column=0, row=row, sticky=(N, E, S), padx=8 )
    ttk.Scale(self._preference_frame, from_=0, to_=MAX_VOLUME, orient=HORIZONTAL, variable=self._c_silence_threshold,  ).grid(column=1, row=row, padx=12, pady=4, sticky=(N, E, W, S))




    self.add_form_row("Record Silence Cutoff", self._c_silence_cutoff )
    self.add_form_row("Save Location", self._c_save_location )
    self.add_form_row("Sample Rate", self._c_sample_rate )
    self.add_form_row("Compress Recordings", self._c_compress, dtype="bool" )

    ttk.Label(self._preference_frame, text="Audio Level").grid(column=0, row=self._pref_form_row_counter.next(), sticky=(N, W, S) )
    self._input_level_indicator = ttk.Progressbar(self._preference_frame, value=50, maximum=MAX_VOLUME, orient=HORIZONTAL, length=200, mode='determinate')
    self._input_level_indicator.grid(column=0, row=self._pref_form_row_counter.next(), columnspan=2, sticky=(N,E,W,S))

    row = self._pref_form_row_counter.next()
    ttk.Label(self._preference_frame, text="Recording Tripped").grid(column=0, row=row, sticky=(N, W, S) )
    self._input_tripped_indicator = ttk.Label(self._preference_frame, padding="4 8 4 4" )
    self._input_tripped_indicator.grid(column=1, row=row, sticky=(N,W,S) )


    self._dialog_button_frame.grid(column=0, row=1, sticky=( N, E, S) )
    ttk.Button(self._dialog_button_frame, text="Reset", command=self._do_reset_form_button_click).grid(column=0, row=0, sticky=(N, E, S) )
    ttk.Button(self._dialog_button_frame, text="Save", command=self._do_save_form_button_click).grid(column=1, row=0, sticky=(N, E, S) )
    #endregion
    self._start_audio_monitor_thread()


  def _reload_config(self):

    self._parse_config = init_config()

    self._c_silence_threshold.set(self._parse_config.getint('DEFAULT', 'silencethreshold'))
    self._c_silence_cutoff.set(self._parse_config.getint('DEFAULT', 'recordsilencecutoff'))
    self._c_save_location.set(self._parse_config.get('DEFAULT', 'savelocation'))
    self._c_sample_rate.set(self._parse_config.getint('DEFAULT', 'samplerate'))
    self._c_compress.set(self._parse_config.getboolean('DEFAULT', 'compress'))


  def _save_config(self):

    self._parse_config.set('DEFAULT', 'silencethreshold', self._c_silence_threshold.get())
    self._parse_config.set('DEFAULT', 'recordsilencecutoff', self._c_silence_cutoff.get())
    self._parse_config.set('DEFAULT', 'savelocation', self._c_save_location.get())
    self._parse_config.set('DEFAULT', 'samplerate', self._c_sample_rate.get())
    self._parse_config.set('DEFAULT', 'compress', self._c_compress.get())

    with open(CONFIG_FILE_NAME, 'w') as config_file:
      self._parse_config.write(config_file)

    pass

  def add_form_row(self, label, binding, dtype='text'):
    """Helper function to add a config parameter to the form. The form will be
    laid out with a text label and a text line entry field to input data.
    :param label: Label to display for this form row.
    :type label: str
    :param binding: variable to databind to the field.
    :type binding: str
    """
    c_row = self._pref_form_row_counter.next()

    ttk.Label(self._preference_frame, text=label).grid(column=0, row=c_row, sticky=(N, E, S) )

    value_field = None
    if dtype == 'text':
      value_field = ttk.Entry(self._preference_frame, textvariable=binding )
    elif dtype == 'bool':
      value_field = ttk.Checkbutton(self._preference_frame, variable=binding)
    value_field.grid(column=1, row=c_row, padx=12, pady=4, sticky=(N,E,S,W))

  def _do_save_form_button_click(self):
    print( "save clicked" )
    self._monitor_should_stop = True
    pass

  def _do_reset_form_button_click(self):
    print( "reset clicked" )
    self._reload_config()
    pass

  def _do_on_window_closing(self):
    print("Waiting to close")
    self._monitor.stop()
    self._monitor.join()
    self._parent.destroy()

  def _start_audio_monitor_thread(self):
    self._monitor = AudioMonitor(self._monitor_queue)
    self._parent.after(100, self._update_monitor)
    #self._monitor = threading.Thread(target=self._listen_to_audio_input, args = ())
    self._monitor.start()

  def _update_monitor(self):
    try:
      value = self._monitor_queue.get(0)
      with self._monitor_queue.mutex:
        self._monitor_queue.queue.clear()
      self._input_level_indicator['value'] = value

      if value > self._c_silence_threshold.get():
        self._input_tripped_indicator.config(background="green")
      else:
        self._input_tripped_indicator.config(background="firebrick1")
    except queue.Empty:
      pass

    self._parent.after(50, self._update_monitor)



class AudioMonitor(threading.Thread):

  def __init__(self, callback):
    super().__init__()
    self._stop_requested = False
    self._callback = callback

  def run(self):
    """Called on another thread to monitor the audio of the selected input device.
    """
    CHUNK_SIZE = 1024
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
        input=True, output=True,
        frames_per_buffer=CHUNK_SIZE)
    print("Stream opened")

    while True:
      snd_data = array('h', stream.read(CHUNK_SIZE))
      if sys.byteorder == 'big':
        snd_data.byteswap()
      #print(f"Min: {min(snd_data)}, Max: {max(snd_data)} ")
      time.sleep(.03)

      if self._stop_requested:
        break
      self._callback.put(max(snd_data))

    stream.stop_stream()
    stream.close()
    p.terminate()
    print("Stream terminated")

  def stop(self):
    """Politely asks the running thread to terminate.
    """
    self._stop_requested = True

if __name__ == "__main__":
    root = Tk()
    appWindow = MainWindow(root)

    root.mainloop()
    pass