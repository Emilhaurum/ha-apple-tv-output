# Changelog

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
