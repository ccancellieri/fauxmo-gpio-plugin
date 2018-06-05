"""pairedfauxmoplugin - base class for paired plugins

In some cases it is useful for two plugin instances to interact with
each other, and this class is a base class to allow that. As an
example (which happens to be the situation for the FauxmoGPIOPlugin),
you have a GPIO plugin and a paired schedule plugin. Let's say the
user has set up the GPIO plugin instance to be named "kitchen light", and of
course he or she could tell Alexa to "turn on the kitchen light".

Then there is a schedule plugin instance which is set to turn the
kitchen light on at 5 am and turn it off at sunrise. Because this
schedule plugin is itself a fauxmo instance, you can also use Alexa to
"turn on kitchen light schedule".

Once the plugins are paired, they interact with each other only by
getting and setting the other's state.

However, in order for this whole approach to work, the plugin
instances need to be able to find each other at runtime. To accomplish
this, one plugin must have the name of the second plugin as a
parameter. The following sample config.json file gives an example:
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
          "timezone": "US/Mountain",
          "latitude": 40.05436,
          "longitude": -105.254826,
          "schedule_events": [ {"trigger": "sunset+20", "value": true},
                               {"trigger": "22:10", "value": false} ]
        }
      ]
    }
  }
}
```

See the doc string for PairedFauxmoPlugins for implementation info.
"""

from fauxmo.plugins import FauxmoPlugin


class PairedFauxmoPlugin(FauxmoPlugin):
    """A base class for paired Fauxmo plugins.

    This base class works as follows:

    1) Both plugins to be paired together must inherit PairedFauxmoPlugin.

    2) Both plugins must call the PairedFauxmoPlugin __init__
    function, typically through a call to `super().__init__(name=name,
    port=port)` at the end of their own __init__ function.  ONE of the
    two plugins must also include the paired_device_name to this call:

    `super().__init__(name=name, port=port, paired_device_name=pair_name)`

    3) While running, either plugin can call get_pair_state() or
    set_pair_state() to get or set the state of the paired device.
    """

    _instances = {}

    def __init__(self,
                 name: str,
                 port: int,
                 paired_device_name: str = None) -> None:
        """Initialize PairedFauxmoPlugin.

        Keyword Args:
            name: Required, device name
            port: Required, port that the Fauxmo associated with this plugin
                  should run on
            paired_device_name: Required from one of the two paired
                  devices. Gives the name of the other device.
        """
        if name in PairedFauxmoPlugin._instances:
            raise ValueError(f"Error: Duplicate plugin name {name}")
        PairedFauxmoPlugin._instances[name] = self

        self.paired_name = paired_device_name
        self.paired_instance = None

        super().__init__(name=name, port=port)

    def _lookup_paired_device(self) -> 'PairedFauxmoPlugin':
        """Return the paired instance for this plugin.

        If the paired instance cannot be found (perhaps it has not yet
        been configured), return None.
        """
        if self.paired_instance is not None:
            return self.paired_instance

        cls = PairedFauxmoPlugin

        if self.paired_name is not None:
            if self.paired_name in cls._instances:
                self.paired_instance = cls._instances[self.paired_name]
                return self.paired_instance
            else:
                return None

        # both paired_name and paired_instance are None; attempt to
        # see if another instance has our instance name as it's
        # paired_name
        for name, inst in cls._instances.items():
            if inst.paired_name == self.name:
                self.paired_name = inst.name
                self.paired_instance = inst
                inst.paired_instance = self
                return inst

        return None

    def get_pair_state(self) -> str:
        """Returns the state of the paired device.

        Should return "on" or "off" if it can be determined, or
        "unknown" if there is no mechanism for determining the device
        state, or if the paired_device cannot be found.
        """
        pair_inst = self._lookup_paired_device()
        if pair_inst is None:
            return "unknown"

        return pair_inst.get_state()

    def set_pair_state(self, state: bool) -> None:
        """Sets the state of the paired device."""
        pair_inst = self._lookup_paired_device()
        if pair_inst is None:
            return
        if state:
            pair_inst.on()
        else:
            pair_inst.off()
