# Apple TV Audio Output

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration that sends an Apple TV's sound to AirPlay 2 speakers. It is tested with
an Apple TV 4K and Sonos speakers on Home Assistant 2026.11.

tvOS only remembers a HomePod as its default audio output. Any other AirPlay speaker has to be picked
again by hand after the Apple TV has slept. Home Assistant's Apple TV integration cannot do it for
you, because it has no action for choosing the audio output. This integration adds that action, so
an automation can pick the speaker every time the Apple TV wakes up.

## Requirements

- Home Assistant 2025.1 or newer (tested on 2026.11).
- The Apple TV set up with the built-in
  [Apple TV integration](https://www.home-assistant.io/integrations/apple_tv/). This integration
  reuses its connection and needs no pairing of its own.
- The Apple TV must be able to reach the speaker over AirPlay. If you can pick the speaker by hand
  on the Apple TV, it will work. See [Troubleshooting](#troubleshooting) if you cannot.

## Installation

### HACS

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/Emilhaurum/ha-apple-tv-output` with the type **Integration**.
3. Install **Apple TV Audio Output** and restart Home Assistant.

### Manual

Copy `custom_components/apple_tv_output` into the `custom_components` folder of your Home Assistant
configuration and restart Home Assistant.

### Set up

Go to **Settings → Devices & services → Add integration** and add **Apple TV Audio Output**. There
is nothing to configure; adding it makes the actions available.

## Actions

Every action takes `entity_id`: the media player of one or more Apple TVs.

| Action | What it does |
| --- | --- |
| `apple_tv_output.set_output` | Sends the sound to the given speakers only. |
| `apple_tv_output.add_output` | Adds the given speakers to the current outputs. |
| `apple_tv_output.remove_output` | Removes the given speakers from the outputs. |
| `apple_tv_output.get_outputs` | Returns the current outputs as response data. |

`speakers` is a list. Each item can be:

- the speaker's AirPlay name, as shown in the Apple TV's audio menu (`Living Room`);
- a media player entity whose name is the same as the AirPlay name (`media_player.living_room`);
- the speaker's AirPlay id (`34:7E:5C:D6:4E:1E`).

Names are looked up with a network scan the first time they are used, which takes a few seconds.
The result is kept until Home Assistant restarts. An id needs no scan; `get_outputs` shows the id of
every speaker that is currently an output.

`set_output` and `add_output` do nothing when all the given speakers are already an output, so
calling them again does not interrupt the sound. Set `force: true` to send the command anyway.

### Example: always play through a Sonos speaker

```yaml
automation:
  - alias: Apple TV sound to the living room speaker
    triggers:
      - trigger: state
        entity_id: media_player.apple_tv
        to:
          - playing
          - paused
          - idle
    actions:
      - action: apple_tv_output.set_output
        data:
          entity_id: media_player.apple_tv
          speakers:
            - Living Room
```

### Example: read the current outputs

```yaml
action: apple_tv_output.get_outputs
data:
  entity_id: media_player.apple_tv
response_variable: result
```

```yaml
media_player.apple_tv:
  outputs:
    - name: Living Room
      identifier: 34:7E:5C:D6:4E:1E
```

## Troubleshooting

**The Apple TV shows "Could not connect to …".** The command arrived, but the Apple TV could not
open the AirPlay connection. This is a network problem: the Apple TV and the speaker are usually on
different networks (VLANs) with a firewall between them. AirPlay 2 needs traffic in both directions
between the two devices. Put them on the same network, or allow all traffic both ways between them.
Picking the speaker by hand on the Apple TV fails in the same way until this is fixed.

**"… is not connected".** Home Assistant has no connection to the Apple TV. Check that the Apple TV
integration shows the device as available. Home Assistant must be able to reach the Apple TV on the
network.

**"No AirPlay speaker named … was found".** The error lists the names that were found. Use one of
those, or use the speaker's AirPlay id. Home Assistant must be able to discover the speaker (mDNS)
for names to work.

## How it works

The Apple TV integration is built on [pyatv](https://pyatv.dev), which can change the output
devices of an Apple TV but is not exposed as an action in Home Assistant. This integration looks up
the pyatv connection that the Apple TV integration already holds and calls it. It relies on
internals of that integration, so a future Home Assistant release could break it; please open an
issue if it does.

## License

MIT
