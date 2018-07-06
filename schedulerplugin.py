"""Fauxmo plugin that controls a different plugin's schedule.

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
          "input_pin": 24,
          "input_pull_dir": "Down",
          "long_press_interval": 800,
          "long_press_action": "toggle_paired_device"
        }
      ]
    },
    "SchedulerPlugin": {
      "path": "/path/to/schedulerplugin.py",
      "DEVICES": [
       {
        "name": "Bedroom Light Schedule",
        "port": 49935,
        "paired_device_name": "Bedroom Light",
        "timezone": "US/Eastern",
        "latitude": 40.443657,
        "longitude": -79.942750,
        "schedule_events": [{"trigger": "sunset", "random": 5, "value": true},
                            {"trigger": "22:10", "value": false} ]
       }
      ]
    }
  }
}
```
"""

from astral import Astral
import pytz
import re
from datetime import datetime, timedelta, time
from random import randint
import asyncio
from fauxmo import logger
from pairedfauxmoplugin import PairedFauxmoPlugin

a = Astral()


class SchedulerPlugin(PairedFauxmoPlugin):
    """Plugin for adding a schedule to another plugin."""

    def __init__(self,
                 name: str,
                 port: int,
                 paired_device: str,
                 schedule_events: list,
                 timezone: str = "UTC",
                 latitude: float = None,
                 longitude: float = None,
                 initial_state: bool = True) -> None:
        """Initialize a SchedulerPlugin instance.

        Args:
            name: Name for this Fauxmo device

            port: Port on which to run this Fauxmo device

            paired_device: Name of the Fauxmo device controlled by
              this schedule instance. The plugin for the paired device
              must also derive from PairedFauxmoPlugin.

            schedule_events: A list of dicts of the form
                  {"trigger": time-str, "random": int, "value": bool}

              time-str should follow the pattern HH:MM[:SS] (with
              hours in 24-hour format), or the patterns "sunrise[+N]",
              "sunrise[-N]", "sunset[+N]" or "sunset[-N]" (where N, if
              specified, is the number of minutes offset from sunrise
              or sunset).

              random, if specified, will cause the actual schedule
                 event to happen randomly between 0 and N minutes
                 after the time specified by time-str.

              value is true to turn on, false to turn off.

            timezone: The local timezone; if not specified, UTC is
              assumed.

            latitude, longitude: Coordinates on which sunrise and
              sunset should be calculated. Must be specified if any
              schedule triggers use sunrise or sunset.

            initial_state: A bool indicating whether the schedule
              is ON or OFF at startup. If not specified, ON is assumed.
        """
        self.state = initial_state
        self.timezone = pytz.timezone(timezone)
        self.latitude = latitude
        self.longitude = longitude

        # Internally, we maintain the self.schedule list, which is a
        # list of schedule events. Each element in the list is a dict
        # of the form specified in the comment for _parse_sched_entry
        self.schedule = []
        if schedule_events:
            for e in schedule_events:
                self.schedule.append(self._parse_sched_entry(e))
        self.reset_schedule()
        logger.info(f"{name} parsed schedule:" + repr(self.schedule))

        self.is_schedule_on = bool(self.schedule)

        self.loop = asyncio.get_event_loop()
        self.loop_running = True
        self.task = self.loop.create_task(self.timer())

        super().__init__(name=name, port=port,
                         paired_device_name=paired_device)
        logger.info(f"Fauxmo schedule device {self.name} initialized")

    def _parse_sched_entry(self, e: dict):
        """Parse an input schedule event.

        The event is assumed to be a dict with three keys: trigger,
        random, and value. Random is optional, the others must be present

        The trigger must follow one of the following formats:

           HH:MM[:SS] (with hours in 24-hour format)
           sunrise[+N] or sunrise[-N]
           sunset[+N] or sunset[-N]

           (where N, if specified, is the number of minutes offset from
           sunrise or sunset).

        Returns: a schedule dict of the form
              (type, offset, time, value, processed)

           'type': one of "fixed", "sunrise", "sunset"
           'offset': for sunrise and sunset events, offset in minutes
              (can be negative)
           'random': int specifying the randomization value in minutes
           'base_time': for fixed events, the datetime.time value for
              this event, in naive format (no timezone)
           'value': true to turn on, false to turn off

           --- values above are not changes except in this function;
           --- values below are changed daily

           'time': TODAY'S datetime.time value for this event, taking
              into account sunrise, sunset, and randomization values
           'processed': true if this event has been processed today, false
              otherwise
        """
        trigger = e['trigger']
        random = 0
        if 'random' in e:
            random = e['random']
        value = e['value']

        # first, try fixed time
        m = re.fullmatch("([0-2]?[0-9]):([0-5][0-9])(:[0-5][0-9])?", trigger)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2))
            second = 0
            if m.group(3):
                second = int(m.group(3)[1:])
            return ({'type': 'fixed',
                     'offset': 0,
                     'random': random,
                     'base_time': time(hour, minute, second),
                     'value': value,
                     'time': None,
                     'processed': False})

        m = re.fullmatch("(sunrise|sunset)([-+]\d+)?", trigger)
        if m:
            offset = 0
            if m.group(2):
                offset = int(m.group(2))
            return({'type': m.group(1),
                    'offset': offset,
                    'random': random,
                    'base_time': None,
                    'value': value,
                    'time': None,
                    'processed': False})

        raise ValueError(f"Illegal schedule trigger: {trigger}")

    async def timer(self):
        "Timer loop to watch for schedule events."

        while (self.loop_running):
            if datetime.now(self.timezone).date() > self.sched_reset_for:
                self.reset_schedule()

            # process any schedule events
            if self.state:
                now = datetime.now(self.timezone).time()
                for e in self.schedule:
                    if now > e['time'] and not e['processed']:
                        self.set_pair_state(e['value'])
                        e['processed'] = True

            # only sleep 1 sec, otherwise teardown time is too long
            await asyncio.sleep(1)

        logger.info(f"{self.name}: timer exiting")

    def close(self) -> None:
        "Shut down cleanly"
        self.loop_running = False
        self.loop.run_until_complete(self.task)
        logger.info(f"{self.name}: Shutdown complete")

    def reset_schedule(self):
        """Run once per day, shortly after midnight. Run through
        self.schedule, setting the 'processed' flag to false for each
        entry, and updating the times for sunrise and sunset events."""

        now = datetime.now(self.timezone)

        for e in self.schedule:
            if e['type'] == 'sunrise':
                utc_tm = a.sunrise_utc(now, self.latitude, self.longitude)
                loc_tm = utc_tm.astimezone(self.timezone)
            elif e['type'] == 'sunset':
                utc_tm = a.sunset_utc(now, self.latitude, self.longitude)
                loc_tm = utc_tm.astimezone(self.timezone)
            elif e['type'] == 'fixed':
                loc_tm = datetime.combine(now.date(), e['base_time'],
                                          self.timezone)
            else:
                raise ValueError(f"Illegal schedule type {e['type']}")

            loc_tm += timedelta(minutes=e['offset'])
            loc_tm += timedelta(seconds=randint(0, e['random']*60))
            # TODO: possible bug here, if the additions above cause
            # loc_tm to roll over midnight - it won't get processed in
            # that case
            e['time'] = loc_tm.time()

            e['processed'] = (e['time'] <= now.time())

        self.sched_reset_for = now.date()

    def on(self) -> bool:
        self.state = True
        logger.info(f"{self.name}: Turned ON")
        return True

    def off(self) -> bool:
        self.state = False
        logger.info(f"{self.name}: Turned OFF")
        return True

    def get_state(self) -> str:
        if self.state:
            return "on"
        return "off"
