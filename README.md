# Apple TV Audio Output

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/Emilhaurum/ha-apple-tv-output)](https://github.com/Emilhaurum/ha-apple-tv-output/releases)
[![Validate](https://github.com/Emilhaurum/ha-apple-tv-output/actions/workflows/validate.yml/badge.svg)](https://github.com/Emilhaurum/ha-apple-tv-output/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/Emilhaurum/ha-apple-tv-output)](LICENSE)

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

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Emilhaurum&repository=ha-apple-tv-output&category=integration)

1. Select the button above to open the repository in HACS, or search for **Apple TV Audio Output**
   in HACS. If HACS does not find it, open the menu, choose **Custom repositories**, and add
   `https://github.com/Emilhaurum/ha-apple-tv-output` with the type **Integration**.
2. Select **Download**, and restart Home Assistant.

### Manual

Copy `custom_components/apple_tv_output` into the `custom_components` folder of your Home Assistant
configuration and restart Home Assistant.

### Set up

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=apple_tv_output)

Select the button above, or go to **Settings → Devices & services → Add integration** and add
**Apple TV Audio Output**. There is nothing to configure; adding it makes the actions available.

The integration's icon shows in Home Assistant 2026.3 and newer, which can show icons that come with
a custom integration.

## Actions

Every action targets one or more Apple TVs. Pick their media player entities, a device, an area or
`all`. Of the entities a device, an area or `all` brings in, only the media players of Apple TVs that
are connected are used: other entities, HomePods and Apple TVs that are off are skipped. An entity
picked by name must be a connected Apple TV.

| Action | What it does |
| --- | --- |
| `apple_tv_output.set_output` | Sends the sound to the given speakers only. |
| `apple_tv_output.add_output` | Adds the given speakers to the current outputs. |
| `apple_tv_output.remove_output` | Removes the given speakers from the outputs. |
| `apple_tv_output.get_outputs` | Returns the current outputs as response data. |

`speakers` is a list. Each item can be:

- the speaker's AirPlay name, as shown in the Apple TV's audio menu (`Living Room`). Upper and
  lower case do not matter;
- a media player entity whose name is the same as the AirPlay name (`media_player.living_room`);
- the speaker's AirPlay id (`34:7E:5C:D6:4E:1E`). It can also be written in lower case, with dashes
  or with nothing between the pairs of digits.

Names are looked up with a network scan, which takes a few seconds. A name that is not known yet is
looked up with a new scan right away, and after an hour the next lookup by name scans again. A
speaker that misses a scan (asleep, say) is still remembered from earlier ones. If a speaker given by
name does not become an output, the integration scans again, in case the speaker has changed, and
resends the command for the speakers whose name now leads to another speaker. An id needs no scan;
`get_outputs` shows the id of every speaker that is currently an output. Any of a speaker's ids can
be used, such as the one Home Assistant shows for a HomePod: if a scan has found the speaker, its
AirPlay id is sent.

Calling an action again does not interrupt the sound:

- `set_output` does nothing when the given speakers are already the only outputs. If any other
  speaker is also playing, the command is sent, and that speaker is dropped.
- `add_output` does nothing when all the given speakers are already an output.
- `remove_output` does nothing when none of the given speakers is an output.

Set `force: true` on `set_output` or `add_output` to send the command anyway.

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
        target:
          entity_id: media_player.apple_tv
        data:
          speakers:
            - Living Room
```

### Example: read the current outputs

```yaml
action: apple_tv_output.get_outputs
target:
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

**"More than one AirPlay speaker is named …".** Two speakers share the name. The error lists their
AirPlay ids: use the id of the one you mean, or rename one of the speakers.

**"… did not report … as an output" in the log.** The command was sent, but the Apple TV did not
start playing to the speaker. This is usually the network problem described above.

**"The Apple TV integration in Home Assistant … works differently".** A Home Assistant update has
changed the Apple TV integration's internals (see below). Please open an issue and say which Home
Assistant version you run.

To see what the integration does, turn on debug logging for it on its page under **Settings →
Devices & services**. The log then shows the speakers each scan finds and the outputs after each
change.

## How it works

The Apple TV integration is built on [pyatv](https://pyatv.dev), which can change the output
devices of an Apple TV but is not exposed as an action in Home Assistant. This integration looks up
the pyatv connection that the Apple TV integration already holds and calls it. It relies on
internals of that integration, so a future Home Assistant release could break it; please open an
issue if it does.

## Known limitations

- It relies on internals of Home Assistant's Apple TV integration (see above). The tests are run
  against the oldest supported and the newest Home Assistant release every week, but a new release
  can still break it.
- Speaker names need mDNS discovery from Home Assistant. Where that does not work, use AirPlay ids.
- Two speakers with the same name cannot be told apart by name; use their ids.
- The Apple TV itself can show up in its own list of outputs. It is ignored when `set_output`
  checks whether the given speakers are already the only outputs.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install pytest-homeassistant-custom-component pyatv ruff mypy
pytest           # tests
ruff check .     # lint
ruff format .    # format
mypy             # type check
```

To release, set `version` in `manifest.json` and add a section for it to `CHANGELOG.md`. Then either
run the **Release** workflow on `main` from the Actions tab, which creates the tag itself, or push a
tag named `v` followed by the version (`v1.1.0`). The workflow checks that the version, the tag and
the changelog match, and publishes a GitHub release, which HACS then offers as an update.

## License

MIT
