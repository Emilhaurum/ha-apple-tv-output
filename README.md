# Apple TV Audio Output

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/Emilhaurum/ha-apple-tv-output)](https://github.com/Emilhaurum/ha-apple-tv-output/releases)
[![Validate](https://github.com/Emilhaurum/ha-apple-tv-output/actions/workflows/validate.yml/badge.svg)](https://github.com/Emilhaurum/ha-apple-tv-output/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/Emilhaurum/ha-apple-tv-output)](LICENSE)

A Home Assistant integration that sends an Apple TV's sound to AirPlay 2 speakers. It is tested with
an Apple TV 4K and Sonos speakers on Home Assistant 2026.11.

tvOS only remembers a HomePod as its default audio output. Any other AirPlay speaker has to be picked
again by hand after the Apple TV has slept. Home Assistant's Apple TV integration cannot do it for
you, because it has no way to choose the audio output. This integration can send the sound to your
speakers every time the Apple TV wakes up, with no automation needed. It also adds actions, a sensor
and a dropdown for the audio output.

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
**Apple TV Audio Output**. There is nothing to fill in; adding it creates the entities and makes the
actions available.

The integration's icon shows in Home Assistant 2026.3 and newer, which can show icons that come with
a custom integration.

## Default speakers

To always play an Apple TV through the same speakers, open **Apple TV Audio Output** under
**Settings → Devices & services** and select **Configure**. Choose the Apple TV, then the speakers.
You can pick speakers found on the network or type an AirPlay name or id.

Whenever that Apple TV wakes up, its sound goes to those speakers. The integration waits up to
30 seconds for Home Assistant's connection to the Apple TV, and tries again a few times if a speaker
does not start playing at once. If you pick another speaker by hand while the Apple TV is on, it is
left alone until the Apple TV next wakes up. To stop, configure the Apple TV again and leave the
speakers empty.

## Entities

Each Apple TV gets a device, named like the Apple TV and connected via its device, with two
entities:

| Entity | What it does |
| --- | --- |
| **Audio outputs** (sensor) | The names of the outputs the Apple TV plays to. Its attributes list each output's name, AirPlay id and volume. Use it on a dashboard or as an automation trigger. |
| **Audio output** (select) | A dropdown of the speakers found on the network. Choosing one sends the sound to that speaker only. When the Apple TV plays to several speakers, nothing is selected. |

The entities update within a few seconds of a change, including changes made on the Apple TV itself.
They are unavailable while Home Assistant is not connected to the Apple TV. A new Apple TV gets its
entities as soon as it is added to the Apple TV integration.

### Example: a dashboard button

```yaml
type: button
name: TV sound to the living room
icon: mdi:speaker-wireless
tap_action:
  action: perform-action
  perform_action: apple_tv_output.set_output
  target:
    entity_id: media_player.apple_tv
  data:
    speakers:
      - Living Room
```

The dropdown can also be added to a dashboard as it is, with an entities card.

## Actions

Every action except `get_speakers` targets one or more Apple TVs. Pick their media player entities, a
device, an area or `all`. Of the entities a device, an area or `all` brings in, only the media
players of Apple TVs that are connected are used: other entities, HomePods and Apple TVs that are off
are skipped. An entity picked by name must be a connected Apple TV.

| Action | What it does |
| --- | --- |
| `apple_tv_output.set_output` | Sends the sound to the given speakers only. |
| `apple_tv_output.add_output` | Adds the given speakers to the current outputs. |
| `apple_tv_output.remove_output` | Removes the given speakers from the outputs. |
| `apple_tv_output.get_outputs` | Returns the current outputs, with the volume of each, as response data. |
| `apple_tv_output.get_speakers` | Returns the AirPlay speakers found on the network. Set `rescan: true` to scan again now. |
| `apple_tv_output.set_volume` | Sets the volume (0 to 1) of one `speaker` the Apple TV plays to. Needs Home Assistant 2026.2 or newer. |

### Speakers

`speakers` is a list (and `speaker` a single item). Each item can be:

- the speaker's AirPlay name, as shown in the Apple TV's audio menu (`Living Room`). Upper and
  lower case do not matter. `get_speakers` lists the names that work;
- a media player entity of the speaker (`media_player.living_room`). When its integration has
  registered the speaker's network address, as Sonos does, that address is used, so the entity's
  name does not matter. Otherwise its name must be the same as the AirPlay name;
- the speaker's AirPlay id (`34:7E:5C:D6:4E:1E`). It can also be written in lower case, with dashes
  or with nothing between the pairs of digits.

Names are looked up with a network scan. The integration scans when it starts and again every hour
in the background, so a call by name does not wait. A name that is not known yet is looked up with a
new scan right away. A speaker that misses a scan (asleep, say) is still remembered from earlier
ones. If a speaker given by name or by entity does not become an output, the integration looks it up
again and resends the command if it now leads to another speaker. Any of a speaker's ids can be used,
such as the one Home Assistant shows for a HomePod: if a scan has found the speaker, its AirPlay id
is sent.

### Options

Calling an action again does not interrupt the sound:

- `set_output` does nothing when the given speakers are already the only outputs. If any other
  speaker is also playing, the command is sent, and that speaker is dropped.
- `add_output` does nothing when all the given speakers are already an output.
- `remove_output` does nothing when none of the given speakers is an output.

`set_output` and `add_output` also take:

| Field | What it does |
| --- | --- |
| `force: true` | Sends the command even when the speakers are already an output. |
| `retries: 3` | If a speaker does not become an output, sends the command again up to this many times, a few seconds apart. Helps right after the Apple TV wakes up. Default 0. |
| `fail_if_not_applied: true` | Makes the action fail when a speaker does not become an output, instead of only logging a warning, so an automation can react. |

`set_output`, `add_output` and `remove_output` can return the outputs before and after the change,
when called with `response_variable`.

### Example: always play through a Sonos speaker

The [default speakers](#default-speakers) setting does this without an automation. As an automation,
for example to add conditions:

```yaml
automation:
  - alias: Apple TV sound to the living room speaker
    triggers:
      - trigger: state
        entity_id: media_player.apple_tv
        from:
          - "off"
          - unavailable
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
          retries: 3
```

### Example: play an announcement elsewhere, then switch back

```yaml
script:
  tv_sound_to_kitchen_for_a_while:
    sequence:
      - action: apple_tv_output.set_output
        target:
          entity_id: media_player.apple_tv
        data:
          speakers:
            - Kitchen
        response_variable: change
      - delay: "00:05:00"
      - action: apple_tv_output.set_output
        target:
          entity_id: media_player.apple_tv
        data:
          speakers: >
            {{ change['media_player.apple_tv'].previous_outputs | map(attribute='identifier') | list }}
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
      volume_level: 0.35
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

**"No AirPlay speaker named … was found".** The error lists the names that were found, as does
`get_speakers`. Use one of those, or use the speaker's AirPlay id. Home Assistant must be able to
discover the speaker (mDNS) for names to work.

**"More than one AirPlay speaker is named …".** Two speakers share the name. The error lists their
AirPlay ids: use the id of the one you mean, or rename one of the speakers.

**"… did not report … as an output" in the log, or "… did not start playing to …".** The command
was sent, but the Apple TV did not start playing to the speaker. This is usually the network problem
described above. Right after the Apple TV wakes up it can also be too early; `retries` helps then.

**A repair notice says the integration does not work with this Home Assistant version.** A Home
Assistant update has changed the Apple TV integration's internals (see below). Please open an issue
and say which Home Assistant version you run.

To see what the integration does, turn on debug logging for it on its page under **Settings →
Devices & services**. The log then shows the speakers each scan finds and the outputs after each
change. When you report a problem, please attach the diagnostics: on the same page, open the menu
and select **Download diagnostics**. AirPlay ids are left out of the download.

## How it works

The Apple TV integration is built on [pyatv](https://pyatv.dev), which can change the output
devices of an Apple TV but is not exposed in Home Assistant. This integration looks up the pyatv
connection that the Apple TV integration already holds and uses it. The entities read the outputs
from that connection every two seconds, which causes no network traffic. It relies on internals of
the Apple TV integration, so a future Home Assistant release could break it; please open an issue if
it does.

## Known limitations

- It relies on internals of Home Assistant's Apple TV integration (see above). The tests are run
  against the oldest supported and the newest Home Assistant release every day, but a new release
  can still break it.
- Speaker names need mDNS discovery from Home Assistant. Where that does not work, use AirPlay ids.
- Two speakers with the same name cannot be told apart by name; use their ids.
- The Apple TV itself can show up in its own list of outputs. It is ignored when `set_output`
  checks whether the given speakers are already the only outputs.
- Setting the volume of one speaker needs Home Assistant 2026.2 or newer, whose pyatv supports it.

## Translations

The integration is in English and Danish. To add a language, copy `custom_components/apple_tv_output/translations/en.json`
to a file named after the language code (`de.json`, `fr.json`, …), translate the text values, and
open a pull request. Keep the keys and the placeholders in braces, such as `{entity_id}`, unchanged;
a test checks that every translation has the same keys and placeholders as the English one.

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
