"""Fauxmo plugin that triggers (and can be triggered by) GPIO pins on
a Raspberry Pi.

When run on a suitably configured Raspberry Pi, this plugin will
emulate an actual Wemo switch. The plugin supports the following
functionality:

1) Exactly one OUTPUT is required.  Two forms of OUTPUT are supported.

   First, an output_pin can be configured in the config file, in which
   case the output pin will be set to ON when the wemo is ON, and vice
   versa.  The canonical use case for this would be to wire up the
   output pin to a relay controlling a light.

   Second, and alternately, an output_command (one each for ON and OFF
   states) can be configured in the config file, in which case the
   appropriate command will be run (via shlex and subprocess.Popen)
   when the wemo's state is toggled.

2) Optionally, one INPUT PIN can be configured. If set, the input_pin
specifies a GPIO input which is tied to a physical, momentary contact
switch. When the switch is pushed, the state of the wemo device will
be toggled.

3) Optionally, one NOTIFICATION PIN can be set. This is a GPIO output,
and its state will be toggled in various ways to reflect the status of
the output, the schedule, and whether the input pin is currently
depressed. The notification pin has the following behavior:

       output on, schedule off:  on
       output on, schedule on:   slow blinking
       output off, schedule off: off
       output off, schedule on:  slow blinking
       switch depressed during long press interval: fast blink
       switch depressed after short press interval: on

   The state of the schedule is derived through the paired Fauxmo
   plugin SchedulerPlugin. If this is not configured then it's as
   if the schedule is always off.

4) Optionally, if an input_pin is configured, a long_press_interval
can also be configured. In this case, if the input_pin is triggered
for longer than the long_press_interval, then the long_press_action
will be triggered. This can be used (just like a real Wemo!) to allow
one switch to control two devices.

This module relies on RPi.GPIO, documented at
  https://sourceforge.net/p/raspberry-gpio-python/wiki/Home/

Pin numbers assume BOARD numbering and not BCM numbering.

Example config:
```
{
  "FAUXMO": {
    "ip_address": "auto"
  },
  "PLUGINS": {
    "FauxmoGpioPlugin": {
      "path": "/path/to/fauxmogpioplugin.py",
      "DEVICES": [
        {
            "name": "Bedroom Light",
            "port": 49915,
            "output_pin": 5,
            "input_pin": 13,
            "input_pull_dir": "Down",
            "notification_pin": 11,
            "long_press_interval": 800,
            "long_press_action": "toggle_paired_device"
        }
      ]
    }
  }
}
```
"""

import RPi.GPIO as GPIO
from fauxmo import logger
from datetime import datetime, timedelta
import asyncio
import shlex
import subprocess
from time import sleep

from pairedfauxmoplugin import PairedFauxmoPlugin


def _run_cmd(cmd: str) -> bool:
    """Run a given command in the background, with no error checking.

    Args:
       cmd: Command to be run
    Returns:
       True if command seems to have run without error
    """
    shlexed_cmd = shlex.split(cmd)
    subprocess.Popen(shlexed_cmd)


class FauxmoGpioPlugin(PairedFauxmoPlugin):
    """Fauxmo Plugin for triggering GPIO lines on a Raspberry Pi."""

    # Class variable to track number of running instances. Used to
    # ensure only the LAST instance calls GPIO.close() to shut down
    # GPIO access
    _num_instances = 0

    def __init__(self,
                 name: str,
                 port: int,
                 type: str = None,
                 state: int = None,
                 output_pin: int = None,
                 output_cmds: list = None,
                 input_pin: int = None,
                 input_pull_dir: str = None,
                 notification_pin: int = None,
                 long_press_interval: int = None,
                 long_press_action: str = None) -> None:
        """Initialize a FauxmoGpioPlugin instance.

        Args:
            name: Name for this Fauxmo device

            port: Port on which to run this instance

            --- must specify one of the following ---

            output_pin: RPi.GPIO pin (using BOARD numbering) to control

            output_cmds: a 2-element string array; first command will
              be run to turn the device "on", second will be run to
              turn it off

            --- from here down the args are optional ---

            input_pin: RPi.GPIO pin (using BOARD numbering) which maps
              to a momentary-contact input switch. When a rising edge
              is detected on this pin, the state of the device will be
              toggled. Default is for the input_pin to not be
              configured.

            input_pull_dir: Either "Down" or "Up". Default is Down.

            notification_pin: RPi.GPIO pin (using BOARD numbering)
              which maps to an LED. The LED will be used for user
              feedback while pressing buttons, and to indicate whether
              the schedule is set or not.

            long_press_interval: duration, in milliseconds, for the
              user to hold down the switch in order to trigger a long
              press. If set, holding the button down for this interval
              will cause the configured long_press_action to be
              executed. If not specified, no long press behavior will
              be recognized.

            long_press_action: the action to be taken when a long
              press occurs. Must be specified if long_press_interval
              is set. Can be either the special string
              "toggle_paired_device", or a command to be run.
        """
        if ( state is not None ):
            self.state = state
        else:
            self.state = False   # True = on, False = off

        # Don't need to validate the output_pin, input_pin etc;
        # RPi.GPIO will throw ValueError if a pin is illegal

        if ( type == "toggle" ):
            self.toggle = True
        else:
            self.toggle = False

        self.output_pin = output_pin
        self.output_cmds = output_cmds

        if self.output_pin is None:
            if self.output_cmds is None or len(self.output_cmds) != 2:
                raise ValueError("Must specify output_pin, or output_cmds")
        else:
            if self.output_cmds is not None:
                raise ValueError("Cannot specify both output_pin and "
                                 "output_cmds")

        self.input_pin = input_pin
        self.notification_pin = notification_pin

        if (not input_pull_dir or input_pull_dir.lower() == "down"):
            self.input_pull_dir = GPIO.PUD_DOWN
        elif input_pull_dir.lower() == "up":
            self.input_pull_dir = GPIO.PUD_UP
        else:
            raise ValueError(f"input_pull_dir must be either Up or Down, "
                             "not {input_pull_dir}")

        self.long_press_interval = long_press_interval
        self.long_press_action = long_press_action

        if self.long_press_interval is not None and \
           self.long_press_action is None:
            raise ValueError("long_press_action required but not found!")

        # in msec, how fast the notification light should pulse when
        # the schedule is set. First number is on time, second is off time
        self.schedule_notification_interval = (50, 1500)

        self.gpio_setup()

        self.loop = asyncio.get_event_loop()
        self.loop_running = True
        if self.input_pin:
            self.task = self.loop.create_task(self.gpio_timer())

        FauxmoGpioPlugin._num_instances += 1

        super().__init__(name=name, port=port)
        logger.info(f"Fauxmo GPIO device {self.name} initialized")

    def gpio_setup(self):
        "Set up the GPIO for the pins we're using"

# TODO CHECKME!!!        GPIO.setmode(GPIO.BOARD)
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Output pin
        if (self.output_pin):
            GPIO.setup(self.output_pin, GPIO.OUT)
            GPIO.output(self.output_pin, self.state)

        # Input pin
        if self.input_pin:
            GPIO.setup(self.input_pin, GPIO.IN,
                       pull_up_down=self.input_pull_dir)

        # Notification pin
        if self.notification_pin:
            GPIO.setup(self.notification_pin, GPIO.OUT)
            GPIO.output(self.notification_pin, self.state)

    def is_schedule_on(self) -> bool:
        """Returns True if a schedule is set.

        Returns True if there is a paired schedule and if the schedule
        is set, False in all other cases."""
        return (self.get_pair_state() == "on")

    def trigger_long_press(self) -> None:
        """Execute the configured long-press action."""
        if self.long_press_action == "toggle_paired_device":
            self.set_pair_state(not self.is_schedule_on())
            return
        _run_cmd(self.long_press_action)

    async def gpio_timer(self):
        """Timer loop to receive switch events. If input_pin is not configured,
        this loop will not run."""

        if self.long_press_interval:
            lp_interval = timedelta(milliseconds=self.long_press_interval)
        else:
            # setting this to 10 minutes is equivalent to disabling it!
            lp_interval = timedelta(seconds=600)

        press_tm = None

        notif_tog_tm = datetime.now()
        notif_delta = 0
        local_is_schedule_on = not self.is_schedule_on()

        while (self.loop_running):
            if GPIO.input(self.input_pin):         # button is depressed
                if not press_tm:
                    press_tm = datetime.now()
                    notif_tog_tm = datetime.now()
                    notif_delta = (40, 80)   # on time in msec, off time

                if (datetime.now() - press_tm) > lp_interval:
                    notif_delta = 0
                    if (self.notification_pin):
                        GPIO.output(self.notification_pin, True)

            elif press_tm:                          # button has been released
                if (datetime.now() - press_tm) < timedelta(milliseconds=50):
                    logger.info(f"{self.name}: very short press, ignoring")
                elif (datetime.now() - press_tm) < lp_interval:  # short press
                    self.set_state(not self.state, "button press")
                else:     # long press
                    self.trigger_long_press()
                press_tm = None
                if self.is_schedule_on():
                    notif_delta = self.schedule_notification_interval
                else:
                    notif_delta = 0
                if (self.notification_pin):
                    GPIO.output(self.notification_pin, self.state)

            if self.is_schedule_on() != local_is_schedule_on:
                if self.is_schedule_on():
                    notif_delta = self.schedule_notification_interval
                    local_is_schedule_on = True
                else:
                    notif_delta = 0
                    local_is_schedule_on = False

            if (notif_delta and self.notification_pin and
                datetime.now() >= notif_tog_tm):
                cur_val = GPIO.input(self.notification_pin)
                if type(notif_delta) is tuple:
                    delta = notif_delta[cur_val]
                else:
                    delta = notif_delta
                notif_tog_tm = datetime.now() + timedelta(milliseconds=delta)
                GPIO.output(self.notification_pin, not cur_val)

            await asyncio.sleep(0.02)

        logger.info(f"{self.name}: gpio_timer exiting")

    def set_state(self, state: bool, reason: str = "unspecified") -> None:
        "Set the plugin into the given state"
        if (state == self.state):
            return
        self.state = state
        if self.output_pin:
            GPIO.output(self.output_pin, self.state)
        elif state:
            _run_cmd(self.output_cmds[0])
        else:
            _run_cmd(self.output_cmds[1])

        if (self.notification_pin):
            GPIO.output(self.notification_pin, self.state)

        newval = "ON" if self.state else "OFF"
        logger.info(f"{self.name}: Turned {newval} on {reason}")

    def close(self) -> None:
        "Shut down cleanly"
        self.loop_running = False
        self.loop.run_until_complete(self.task)
        self.set_state(False, "shutdown")
        FauxmoGpioPlugin._num_instances -= 1
        if (FauxmoGpioPlugin._num_instances == 0):
            GPIO.cleanup()
        logger.info(f"{self.name}: Shutdown complete")

    def on(self) -> bool:
        "Run the on command.  Returns true if command succeeded"
        if (self.toggle):
             self._toggle(True)
        else:
             self.set_state(True, "wemo command")
        return True

    def off(self) -> bool:
        "Run the on command.  Returns true if command succeeded"
        if (self.toggle):
             self._toggle(False)
        else:
             self.set_state(False, "wemo command")
        return True

    def _toggle(self, state: bool) -> None:
        "Run the TOGGLE command.  Returns true if command succeeded"
        GPIO.output(self.output_pin, False)
        logger.info(f"{self.name}: Turned to --> {not self.state}")
        sleep(0.1)
        GPIO.output(self.output_pin, True)
        logger.info(f"{self.name}: Turned back to --> {self.state}")
        self.state = state

    def get_state(self) -> str:
        "Get device state. Returns one of the strings 'on' or 'off'"
#        return "unknown"
        if self.state:
            return "on"
        else:
            return "off"
