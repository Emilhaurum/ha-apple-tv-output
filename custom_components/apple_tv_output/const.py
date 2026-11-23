"""Constants for the Apple TV Audio Output integration."""

DOMAIN = "apple_tv_output"
APPLE_TV_DOMAIN = "apple_tv"

ATTR_SPEAKERS = "speakers"
ATTR_SPEAKER = "speaker"
ATTR_FORCE = "force"
ATTR_RETRIES = "retries"
ATTR_FAIL_IF_NOT_APPLIED = "fail_if_not_applied"
ATTR_RESCAN = "rescan"
ATTR_VOLUME_LEVEL = "volume_level"

SERVICE_SET_OUTPUT = "set_output"
SERVICE_ADD_OUTPUT = "add_output"
SERVICE_REMOVE_OUTPUT = "remove_output"
SERVICE_GET_OUTPUTS = "get_outputs"
SERVICE_GET_SPEAKERS = "get_speakers"
SERVICE_SET_VOLUME = "set_volume"

# Config entry data of a paired Apple TV.
CONF_ADDRESS = "address"
CONF_IDENTIFIERS = "identifiers"
CONF_CREDENTIALS = "credentials"

# Options: the Apple TV's default speakers. (A 1.x entry stored them by the registry id of the Apple TV
# integration's media player instead.)
CONF_DEFAULT_SPEAKERS = "default_speakers"

ISSUE_LEGACY_ENTRY = "legacy_entry"

# How long a network scan for AirPlay speakers may take, in seconds.
SCAN_TIMEOUT = 4

# How long the speakers found by a scan are trusted before the next lookup by name scans again.
CACHE_TTL = 3600

# How long to wait, after a command, for the Apple TV to report the new outputs, in seconds.
OUTPUT_SETTLE_TIME = 2.0

# How long to wait before sending a command again when a speaker did not become an output, in seconds.
RETRY_DELAY = 3.0
MAX_RETRIES = 5

# Default speakers: how many times the command is sent again when a speaker does not start playing.
DEFAULT_SPEAKERS_RETRIES = 3

# Reconnecting to an Apple TV: the first and the longest wait between attempts, in seconds.
RECONNECT_MIN = 5
RECONNECT_MAX = 300

# An Apple TV may drop the connection while it sleeps. Reconnecting to one that is on counts as waking
# up when it was off before the connection was lost, or when the connection was gone this long (seconds).
WAKE_AFTER_OUTAGE = 300
