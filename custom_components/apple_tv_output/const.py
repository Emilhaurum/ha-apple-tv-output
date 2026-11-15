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

# Options: default speakers per Apple TV, by the entity registry id of its media player.
CONF_DEFAULT_SPEAKERS = "default_speakers"

ISSUE_UNSUPPORTED_VERSION = "unsupported_version"

# How long a network scan for AirPlay speakers may take, in seconds.
SCAN_TIMEOUT = 4

# How long the speakers found by a scan are trusted before the next lookup by name scans again.
CACHE_TTL = 3600

# How long to wait, after a command, for the Apple TV to report the new outputs, in seconds.
OUTPUT_SETTLE_TIME = 2.0

# How long to wait before sending a command again when a speaker did not become an output, in seconds.
RETRY_DELAY = 3.0
MAX_RETRIES = 5

# How often the entities read the outputs from the connection (no network traffic), in seconds.
POLL_INTERVAL = 2

# Default speakers: how many times a woken Apple TV is retried, and how long to wait for its connection.
DEFAULT_SPEAKERS_RETRIES = 3
CONNECT_WAIT = 30
