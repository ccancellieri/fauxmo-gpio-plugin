# fauxmo-gpio-plugins

There are two Fauxmo plugins here. Together they allow you to build a
relatively complete Wemo on your own Raspberry Pi hardware.

## Introduction

As a test project, I wanted to develop a better Wemo plug. See this
[blog post](https://cardinalpeak.com/blog/where-there-is-no-vision/)
for the full post, but my main criticism of Belkin was contained in
this sentence:

>Ideally, the Wi-Fi functionality would be built into the lamp. For
>this to happen, Belkin et al need to sell modules to the likes of
>Pottery Barn (or, more realistically, Pottery Barn’s lamp
>suppliers). Failing that, we need a fashionable-looking box that sits
>on the table, beside or under the lamp, that allows direct control of
>the light by pressing a button.

So I cobbled together a Raspberry Pi Zero W with a 120V relay and a
momentary switch, and built the whole thing in a very nice (if I do
say so myself) walnut box that measures 8 in square by 2 in tall and
serves as a stand for the lamp that it controls. My "Wemo" is
controllable by Alexa (thanks to the great
[Fauxmo](https://github.com/n8henrie/fauxmo-plugins) project). It also
has a schedule.

In order to make this work, I developed two fauxmo plugins, details
below.

## Fauxmo GPIO Plugin

This Fauxmo plugin triggers (and can be triggered by) GPIO pins on a
Raspberry Pi. The plugin supports the following functionality:

-- First, one *output* is required. Two types of output are supported.

   First, an output_pin can be configured in the config file, in which
   case the output pin will be set to ON when the wemo is ON, and vice
   versa. The canonical use case for this would be to wire up the
   output pin to a relay controlling a light.

   Second, and alternately, an output_command (one each for ON and OFF
   states) can be configured in the config file, in which case the
   appropriate command will be run when the wemo's state is
   toggled. In some ways this duplicates the CommandLinePlugin found
   in the [fauxmo-plugins](https://github.com/n8henrie/fauxmo-plugins)
   project, but there are some differences.

-- Second, and optionally, one *input pin* can be configured. If set,
the input_pin specifies a GPIO input which is tied to a physical,
momentary contact switch. When the switch is pushed, the state of the
Wemo device will be toggled.

-- Third, also optionally, one *notification pin* can be set. This is a
GPIO output, and its state will be toggled in various ways to reflect
the status of the output, the schedule, and whether the input pin is
currently depressed. The notification pin has the following behavior:

       output on, schedule off:  on
       output on, schedule on:   slow blinking
       output off, schedule off: off
       output off, schedule on:  slow blinking
       switch depressed during long press interval: fast blink
       switch depressed after short press interval: on

   The state of the schedule is derived through the paired Fauxmo
   plugin SchedulerPlugin. If this is not configured then it's as
   if the schedule is always off.

-- Finally, if an input_pin is configured, a long_press_interval can
also be configured. In this case, if the input_pin is triggered for
longer than the long_press_interval, then the long_press_action will
be triggered. This can be used (just like a real Wemo!) to allow one
switch to control two devices.

See the documentation in fauxmogpioplugin.py for more.

## Scheduler Plugin

SchedulerPlugin is a helper plugin: It allows you to add a schedule to
another Fauxmo plugin. It supports the following functionality:

- Turn on/off at a given time of day (e.g., turn on at 6:05 pm)

- Turn on/off at a specified offset from sunrise or sunset (e.g., turn
  off 20 minutes after sunset).

- In addition, schedule events support randomization, where the actual
  turn on/off event will happen within a random window specified by
  the user (e.g., turn off sometime within the 20 minutes after 10 pm).

In order to use the sunrise/sunset functionality, the user must know
the latitude and longitude. This is readily available via Google Maps
lookup.

Because SchedulerPlugin is itself a Fauxmo plugin instance, the
schedule itself can be controlled via Alexa. So, for instance, you
might have a FauxmoGPIOPlugin named "Living Room Light", which
controls a lamp in your living room. Then to control this device, you
can have a SchedulerPlugin named "Living Room Light Schedule". You can
say "Alexa, turn on the Living Room Light Schedule" to enable the
schedule, and conversely to disable it. This can be useful, for
instance, when leaving for vacation.

See the documentation in fauxmogpioplugin.py for more.

## Installing

To install and configure:

1) Follow the Fauxmo [installation directions](https://github.com/n8henrie/fauxmo)

2) `pip install RPi.GPIO Astral`

3) `git clone https://github.com/howdypierce/fauxmo-gpio-plugin.git`

4) Edit config-sample.json to values suitable for your use, and start
fauxmo using your edited .json file: `fauxmo -c /path/to/config.json -vv`

## Additional Links

- [Fauxmo](https://github.com/n8henrie/fauxmo-plugins) by Nathan
  Henrie. You need to install Fauxmo in order to use my plugins.

- [Fauxmo-plugins](https://github.com/n8henrie/fauxmo-plugins), also
  by Nathan Henrie. Note you don't need to install this project in
  order to use my code, but there is additional documentation and
  examples at this link that explain what's going on.

## Thanks

This whole project was made much easier by the Fauxmo project, which
is extremely well done. Thanks to Nathan Henrie and @makermusings for
that.

