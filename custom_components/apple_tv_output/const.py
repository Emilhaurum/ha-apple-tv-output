"""Constants for the Apple TV Audio Output integration."""

DOMAIN = "apple_tv_output"
APPLE_TV_DOMAIN = "apple_tv"

ATTR_SPEAKERS = "speakers"
ATTR_FORCE = "force"

SERVICE_SET_OUTPUT = "set_output"
SERVICE_ADD_OUTPUT = "add_output"
SERVICE_REMOVE_OUTPUT = "remove_output"
SERVICE_GET_OUTPUTS = "get_outputs"

# How long a network scan for AirPlay speakers may take, in seconds.
SCAN_TIMEOUT = 4

# How long the speakers found by a scan are trusted before the next lookup by name scans again.
CACHE_TTL = 3600
