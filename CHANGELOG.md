# Changelog

## [1.2.2]

### Documentation

- Screenshots of the Set audio output action and of the Audio output and Audio outputs entities in
  the README (#18).

## [1.2.1]

### Fixed

- A speaker's volume showed as 0 in `get_outputs`, the Audio outputs sensor and diagnostics until it
  had been changed, because the Apple TV only reports a speaker's volume after a change. The volume is
  now left out until it has been reported.

## [1.2.0]

### Added

- Default speakers: under **Configure**, choose speakers an Apple TV should always play to. Its sound
  is sent there whenever it wakes up, with no automation needed (#5).
- A device for each Apple TV with two entities: an **Audio outputs** sensor showing the current
  outputs (#10), and an **Audio output** dropdown to choose the speaker from a dashboard (#11).
- `get_speakers` action, which lists the AirPlay speakers found on the network (#7).
- `set_volume` action, which sets the volume of one output speaker, and the volume of each output in
  `get_outputs` (Home Assistant 2026.2 and newer) (#12).
- `retries` field on `set_output` and `add_output`, to try again when a speaker does not become an
  output, for example right after the Apple TV wakes up (#13).
- `fail_if_not_applied` field, to make the action fail instead of only logging a warning (#14).
- `set_output`, `add_output` and `remove_output` can return the outputs before and after the change
  (#16).
- A repair notice when a Home Assistant update changes the Apple TV integration in a way this
  integration does not expect, and a diagnostics download for bug reports (#15).
- Danish translation, and a guide for contributing translations in the README (#17).
- A dashboard button example in the README (#18).

### Changed

- A speaker given as a media player entity is found by its device's network address when its
  integration registered one, as Sonos does, so its name no longer has to match the AirPlay name. If
  the address does not work, the name is tried (#8).
- The network is scanned for speakers when the integration starts and every hour in the background,
  so calls by name no longer wait for a scan (#9).

## [1.1.0]

### Changed

- The actions take a target, so an Apple TV can be picked by entity, device, area or `all`. Of the
  entities a device, an area or `all` brings in, HomePods and Apple TVs that are not connected are
  skipped. Calls that pass `entity_id` in `data` keep working.
- Error messages can be translated.

### Fixed

- `set_output` did nothing when the given speakers were already an output while another speaker also
  played. It now does nothing only when they are the only outputs, so the other speaker is dropped.
- An AirPlay id written in lower case or without colons was not recognised as a current output, so
  the command was sent again and could interrupt the sound.
- Speakers looked up by name were sent by their main pyatv id. For a HomePod, that is not the AirPlay
  id the Apple TV expects. The AirPlay id is now used, also when another of the speaker's ids is given.
- Speakers found by a scan were kept until Home Assistant restarted. Names are now looked up again
  after an hour, and a speaker that does not become an output is looked up again at once. Calls that
  need a scan at the same time share one.
- Two speakers with the same name were silently confused. This is now an error that lists their ids.
- With several Apple TVs, a wrong target was found only after the earlier ones had been changed. All
  targets are now checked first.

### Added

- A clear error and log message when a Home Assistant update changes the Apple TV integration's
  internals.
- A warning in the log when the Apple TV does not report a speaker as an output after the command.
- Tests, linting and type checking, run in CI against the oldest supported and the newest Home
  Assistant release.
- A release workflow and Dependabot updates for the GitHub Actions.
- Ready for the HACS default store: integration categories, a trimmed icon, buttons that open the
  repository in HACS and start the setup, and issue templates.

## [1.0.0]

- First release.
