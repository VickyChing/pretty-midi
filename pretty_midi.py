# -*- coding: utf-8 -*-
# <nbformat>3.0</nbformat>

# <codecell>

'''
Utility functions for handling MIDI data in an easy to read/manipulate format
'''

# <codecell>

import midi
import numpy as np

# <codecell>

class PrettyMIDI(object):
    '''
    A container for MIDI data in a nice format.
    
    Members:
        instruments - list of pretty_midi.Instrument objects, corresponding to the instruments which play in the MIDI file
    '''
    def __init__(self, midi_data):
        '''
        Initialize the PrettyMIDI container with some midi data
        
        Input:
            midi_data - midi.FileReader object
        '''
        # Convert tick values in midi_data to absolute, a useful thing.
        midi_data.make_ticks_abs()
        
        # Store the resolution for later use
        self.resolution = midi_data.resolution
        
        # Populate the list of tempo changes (tick scales)
        self._get_tempo_changes(midi_data)
        # Update the array which maps ticks to time
        max_tick = max([max([event.tick for event in track]) for track in midi_data]) + 1
        self._update_tick_to_time(max_tick)
        # Check that there are no tempo change events on any tracks other than track 0
        if sum([sum([event.name == 'Set Tempo' for event in track]) for track in midi_data[1:]]):
            print "Warning - tempo change events found on non-zero tracks.  This is not a valid type 0 or type 1 MIDI file.  Timing may be wrong."
            
        # Populate the list of instruments
        self._get_instruments(midi_data)
        
    def _get_tempo_changes(self, midi_data):
        '''
        Populates self.tick_scales with tuples of (tick, tick_scale)
        
        Input:
            midi_data - midi.FileReader object
        '''
        # MIDI data is given in "ticks".  We need to convert this to clock seconds.
        # The conversion factor has to do with the BPM, which may change over time.
        # So, create a list of tuples, (time, tempo) which denotes the tempo over time
        # By default, set the tempo to 120 bpm, starting at time 0
        self.tick_scales = [(0, 60.0/(120.0*midi_data.resolution))]
        # Keep track of the absolute tick value of the previous tempo change event
        lastTick = 0
        # For SMF file type 0, all events are on track 0.
        # For type 1, all tempo events should be on track 1.
        # Everyone ignores type 2.
        # So, just look at events on track 0
        for event in midi_data[0]:
            if event.name == 'Set Tempo':
                # Only allow one tempo change event at the beginning
                if event.tick == 0:
                    self.tick_scales = [(0, 60.0/(event.get_bpm()*midi_data.resolution))]
                else:
                    # Get time and BPM up to this point
                    last_tick, last_tick_scale = self.tick_scales[-1]
                    tick_scale = 60.0/(event.get_bpm()*midi_data.resolution)
                    # Ignore repetition of BPM, which happens often
                    if tick_scale != last_tick_scale:
                        self.tick_scales.append( (event.tick, tick_scale) )
    
    def _update_tick_to_time(self, max_tick):
        '''
        Creates tick_to_time, an array which maps ticks to time, from tick 0 to max_tick
        
        Input:
            max_tick - last tick to compute time for
        '''
        # Allocate tick to time array - indexed by tick from 0 to max_tick
        self.tick_to_time = np.zeros( max_tick )
        # Keep track of the end time of the last tick in the previous interval
        last_end_time = 0
        # Cycle through intervals of different tempii
        for (start_tick, tick_scale), (end_tick, _) in zip(self.tick_scales[:-1], self.tick_scales[1:]):
            # Convert ticks in this interval to times
            self.tick_to_time[start_tick:end_tick + 1] = last_end_time + tick_scale*np.arange(end_tick - start_tick + 1)
            # Update the time of the last tick in this interval
            last_end_time = self.tick_to_time[end_tick]
        # For the final interval, use the final tempo setting and ticks from the final tempo setting until max_tick
        start_tick, tick_scale = self.tick_scales[-1]
        self.tick_to_time[start_tick:] = last_end_time + tick_scale*np.arange(max_tick - start_tick)
        
    def _get_instruments(self, midi_data):
        '''
        Populates the list of instruments in midi_data.
        
        Input:
            midi_data - midi.FileReader object
        '''
        # Initialize empty list of instruments
        self.instruments = []
        for track in midi_data:
            # Keep track of last note on location: key = (instrument, is_drum, note), value = (note on time, velocity)
            last_note_on = {}
            # Keep track of pitch bends: key = (instrument, is_drum) value = (pitch bend time, pitch bend amount)
            pitch_bends = {}
            # Keep track of which instrument is playing in each channel - initialize to program 0 for all channels
            current_instrument = np.zeros( 16, dtype=np.int )
            for event in track:
                # Look for program change events
                if event.name == 'Program Change':
                    # Update the instrument for this channel
                    current_instrument[event.channel] = event.data[0]
                # Note ons are note on events with velocity > 0
                elif event.name == 'Note On' and event.velocity > 0:
                    # Check whether this event is for the drum channel
                    is_drum = (event.channel == 9)
                    # Store this as the last note-on location
                    last_note_on[(current_instrument[event.channel], is_drum, event.pitch)] = (self.tick_to_time[event.tick], event.velocity)
                # Note offs can also be note on events with 0 velocity
                elif event.name == 'Note Off' or (event.name == 'Note On' and event.velocity == 0):
                    # Check whether this event is for the drum channel
                    is_drum = (event.channel == 9)
                    # Check that a note-on exists (ignore spurious note-offs)
                    if (current_instrument[event.channel], is_drum, event.pitch) in last_note_on:
                        # Get the start/stop times and velocity of this note
                        start, velocity = last_note_on[(current_instrument[event.channel], is_drum, event.pitch)]
                        end = self.tick_to_time[event.tick]
                        # Check that the instrument exists
                        instrument_exists = False
                        for instrument in self.instruments:
                            # Find the right instrument
                            if instrument.program == current_instrument[event.channel] and instrument.is_drum == is_drum:
                                instrument_exists = True
                                # Add this note event
                                instrument.events.append(Note(velocity, event.pitch, start, end))
                        # Create the instrument if none was found
                        if not instrument_exists:
                            # Create a new instrument
                            self.instruments.append(Instrument(current_instrument[event.channel], is_drum))
                            instrument = self.instruments[-1]
                            # Add the note to the new instrument
                            instrument.events.append(Note(event.velocity, event.pitch, start, end))
                        # Remove the last note on for this instrument
                        del last_note_on[(current_instrument[event.channel], is_drum, event.pitch)]
                # Store pitch bends
                elif event.name == 'Pitch Wheel':
                    # Check whether this event is for the drum channel
                    is_drum = (event.channel == 9)
                    # Convert to relative pitch in semitones
                    pitch_bend = 2*event.pitch/8192.0
                    for instrument in self.instruments:
                        # Find the right instrument
                        if instrument.program == current_instrument[event.channel] and instrument.is_drum == is_drum:
                            # Store pitch bend information
                            instrument.pitch_changes.append((self.tick_to_time[event.tick], pitch_bend))
        
    def get_tempii(self):
        '''
        Return arrays of tempo changes and their times.  This is direct from the MIDI file.
        
        Output:
            tempo_change_times - Times, in seconds, where the tempo changes.
            tempii - np.ndarray of tempos, same size as tempo_change_times
        '''
        # Pre-allocate return arrays
        tempo_change_times = np.zeros(len(self.tick_scales))
        tempii = np.zeros(len(self.tick_scales))
        for n, (tick, tick_scale) in enumerate(self.tick_scales):
            # Convert tick of this tempo change to time in seconds
            tempo_change_times[n] = self.tick_to_time[tick]
            # Convert tick scale to a tempo
            tempii[n] = 60.0/(tick_scale*self.resolution)
        return tempo_change_times, tempii
        
    def get_beats(self):
        '''
        Return a list of (probably correct) beat locations in the MIDI file
        
        Output:
            beats - np.ndarray of beat locations, in seconds
        '''
    
    def get_onsets(self):
        '''
        Return a list of the times of all onsets of all notes from all instruments.
        
        Output:
            onsets - np.ndarray of onset locations, in seconds
        '''
        onsets = np.array([])
        # Just concatenate onsets from all the instruments
        for instrument in self.instruments:
            onsets = np.append( onsets, instrument.get_onsets() )
        # Return them sorted (because why not?)
        return np.sort( onsets )
    
    def get_piano_roll(self, times=None):
        '''
        Get the MIDI data in piano roll notation.
        
        Input:
            times - times of the start of each column in the piano roll, default None which is np.arange(0, event_times.max(), 1/100.0)
        Output:
            piano_roll - piano roll of MIDI data, flattened across instruments, np.ndarray of size 128 x times.shape[0]
        '''
        # Get piano rolls for each instrument
        piano_rolls = [i.get_piano_roll(times=times) for i in self.instruments]
        # Allocate piano roll, # columns is max of # of columns in all piano rolls
        piano_roll = np.zeros( (128, np.max([p.shape[1] for p in piano_rolls])), dtype=np.int16 )
        # Sum each piano roll into the aggregate piano roll
        for roll in piano_rolls:
            piano_roll[:, :roll.shape[1]] += roll
        return piano_roll

    def get_chroma(self, times=None):
        '''
        Get the MIDI data as a sequence of chroma vectors.
        
        Input:
            times - times of the start of each column in the chroma matrix, default None which is np.arange(0, event_times.max(), 1/1000.0)
        Output:
            chroma - chroma matrix, flattened across instruments, np.ndarray of size 12 x times.shape[0]
        '''
        # First, get the piano roll
        piano_roll = self.get_piano_roll(times=times)
        # Fold into one octave
        chroma_matrix = np.zeros((12, piano_roll.shape[1]))
        for note in range(12):
            chroma_matrix[note, :] = np.sum(piano_roll[note::12], axis=0)
        return chroma_matrix

    def synthesize(self, fs=44100, wave=np.sin):
        '''
        Synthesize the pattern using some waveshape.  Ignores drum track.
        
        Input:
            fs - Sampling rate
            wave - Function which returns a periodic waveform, e.g. np.sin, scipy.signal.square, etc.
        Output:
            synthesized - Waveform of the MIDI data, synthesized at fs
        '''
        # Get synthesized waveform for each instrument
        waveforms = [i.synthesize(fs=fs, wave=wave) for i in self.instruments]
        # Allocate output waveform, with #sample = max length of all waveforms
        synthesized = np.zeros(np.max([w.shape[0] for w in waveforms]))
        # Sum all waveforms in
        for waveform in waveforms:
            synthesized[:waveform.shape[0]] += waveform
        # Normalize
        synthesized /= np.abs(synthesized).max()
        return synthesized

# <codecell>

class Instrument(object):
    '''
    Object to hold event information for a single instrument
    
    Members:
        program - The program number of this instrument.
        is_drum - Is the instrument a drum instrument (channel 9)?
        events - List of Note objects
        pitch_changes - List of pitch adjustments, in semitones (via the pitch wheel).  Tuples of (absolute time, relative pitch adjustment)
    '''
    def __init__(self, program, is_drum=False):
        '''
        Create the Instrument.  events gets initialized to empty list, fill with (Instrument).events.append( event )
        
        Input:
            program - MIDI program number (instrument index)
            is_drum - Is the instrument a drum instrument (channel 9)? Default False
        '''
        self.program = program
        self.is_drum = is_drum
        self.events = []
        self.pitch_changes = []
    
    def get_onsets(self):
        '''
        Get all onsets of all notes played by this instrument.
        
        Output:
            onsets - np.ndarray of all onsets
        '''
        onsets = []
        # Get the note-on time of each note played by this instrument
        for note in self.events:
            onsets.append( note.start )
        # Return them sorted (because why not?)
        return np.sort( onsets )
    
    def get_piano_roll(self, times=None):
        '''
        Get a piano roll notation of the note events of this instrument.
        
        Input:
            times - times of the start of each column in the piano roll, default None which is np.arange(0, event_times.max(), 1/100.0)
        Output:
            piano_roll - Piano roll matrix, np.ndarray of size 128 x times.shape[0]
        '''
        # If there are no events, return an empty matrix
        if self.events == []:
            return np.array([[]]*128)
        # Get the end time of the last event
        end_time = np.max([note.end for note in self.events])
        # Sample at 100 Hz
        fs = 100
        # Allocate a matrix of zeros - we will add in as we go
        piano_roll = np.zeros((128, fs*end_time), dtype=np.int16)
        # Drum tracks don't have pitch, so return a matrix of zeros
        if self.is_drum:
            if times is None:
                return piano_roll
            else:
                return np.zeros((128, times.shape[0]), dtype=np.int16)
        # Add up piano roll matrix, note-by-note
        for note in self.events:
            # Should interpolate
            piano_roll[note.pitch, int(note.start*fs):int(note.end*fs)] += note.velocity

        # Process pitch changes
        for ((start, bend), (end, _)) in zip( self.pitch_changes, self.pitch_changes[1:] + [(end_time, 0)] ):
            # Piano roll is already generated with everything bend = 0
            if np.abs( bend ) < 1/8192.0:
                continue
            # Get integer and decimal part of bend amount
            bend_int = int( np.sign( bend )*np.floor( np.abs( bend ) ) )
            bend_decimal = np.abs( bend - bend_int )
            # Construct the bent part of the piano roll
            bent_roll = np.zeros( (128, int(end*fs) - int(start*fs)) )
            # Easiest to process differently depending on bend sign
            if bend >= 0:
                # First, pitch shift by the int amount
                if bend_int is not 0:
                    bent_roll[bend_int:] = piano_roll[:-bend_int, int(start*fs):int(end*fs)]
                else:
                    bent_roll = piano_roll[:, int(start*fs):int(end*fs)]
                # Now, linear interpolate by the decimal place
                bent_roll[1:] = (1 - bend_decimal)*bent_roll[1:] + bend_decimal*bent_roll[:-1]
            else:
                # Same procedure as for positive bends
                if bend_int is not 0:
                    bent_roll[:bend_int] = piano_roll[-bend_int:, int(start*fs):int(end*fs)]
                else:
                    bent_roll = piano_roll[:, int(start*fs):int(end*fs)]
                bent_roll[:-1] = (1 - bend_decimal)*bent_roll[:-1] + bend_decimal*bent_roll[1:]
            # Store bent portion back in piano roll
            piano_roll[:, int(start*fs):int(end*fs)] = bent_roll
        
        if times is None:
            return piano_roll
        piano_roll_integrated = np.zeros((128, times.shape[0]), dtype=np.int16)
        # Convert to column indices
        times = times*fs
        for n, (start, end) in enumerate(zip(times[:-1], times[1:])):
            # Each column is the mean of the columns in piano_roll
            piano_roll_integrated[:, n] = np.mean(piano_roll[:, start:end], axis=1)
        return piano_roll_integrated

    def get_chroma(self, times=None):
        '''
        Get a chroma matrix for the note events in this instrument.
        
        Input:
            times - times of the start of each column in the chroma matrix, default None which is np.arange(0, event_times.max(), 1/1000.0)
        Output:
            chroma - chroma matrix, np.ndarray of size 12 x times.shape[0]
        '''
        # First, get the piano roll
        piano_roll = self.get_piano_roll(times=times)
        # Fold into one octave
        chroma_matrix = np.zeros((12, piano_roll.shape[1]))
        for note in range(12):
            chroma_matrix[note, :] = np.sum(piano_roll[note::12], axis=0)
        return chroma_matrix

    def synthesize(self, fs=44100, wave=np.sin):
        '''
        Synthesize the instrument's notes using some waveshape.  For drum instruments, returns zeros.
        
        Input:
            fs - Sampling rate
            wave - Function which returns a periodic waveform, e.g. np.sin, scipy.signal.square, etc.
        Output:
            synthesized - Waveform of the MIDI data, synthesized at fs.  Not normalized!
        '''
        # Pre-allocate output waveform
        synthesized = np.zeros(fs*(max([n.end for n in self.events]) + 1))
        # If we're a percussion channel, just return the zeros
        if self.is_drum:
            return synthesized
        # This is a simple way to make the end of the notes fade-out without clicks
        fade_out = np.linspace( 1, 0, .1*fs )
        # Add in waveform for each note
        for note in self.events:
            # Indices in samples of this note
            start = int(fs*note.start)
            end = int(fs*note.end)
            # Get frequency of note from MIDI note number
            frequency = 440*(2.0**((note.pitch - 69)/12.0))
            # Synthesize using wave function at this frequency
            note_waveform = wave(2*np.pi*frequency*np.arange(end - start)/fs)
            # Apply an exponential envelope
            envelope = np.exp(-np.arange(end - start)/(1.0*fs))
            # Make the end of the envelope be a fadeout
            if envelope.shape[0] > fade_out.shape[0]:
                envelope[-fade_out.shape[0]:] *= fade_out
            else:
                envelope *= np.linspace( 1, 0, envelope.shape[0] )
            # Multiply by velocity (don't think it's linearly scaled but whatever)
            envelope *= note.velocity
            # Add in envelope'd waveform to the synthesized signal
            synthesized[start:end] += envelope*note_waveform
        return synthesized
    
    def __repr__(self):
        return 'Instrument(program={}, is_drum={})'.format(self.program, self.is_drum, len(self.events))
        

# <codecell>

class Note(object):
    '''
    A note event.
    
    Members:
        velocity - Note velocity
        pitch - Note pitch, as a MIDI note number
        start - Note on time, absolute, in seconds
        end - Note off time, absolute, in seconds
    '''
    def __init__(self, velocity, pitch, start, end):
        '''
        Create a note object.  pitch_changes is initialized to [], add pitch changes via (Note).pitch_changes.append
        
        Input:
            velocity - Note velocity
            pitch - Note pitch, as a MIDI note number
            start - Note on time, absolute, in seconds
            end - Note off time, absolute, in seconds
        '''
        self.velocity = velocity
        self.pitch = pitch
        self.start = start
        self.end = end
    
    def __repr__(self):
        return 'Note(start={:f}, end={:f}, pitch={}, velocity={})'.format(self.start, self.end, self.pitch, self.velocity)

