"""Constants for the Aqualisa integration."""

DOMAIN = "aqualisa"

BASE_URL_UK = "https://appuser.aqualisa.co.uk/api/v1"
BASE_URL_EU = "https://appuser-eu.aqualisa.co.uk/api/v1"

# Firebase config from the Aqualisa Android APK
FCM_SENDER_ID = "134284945450"
FCM_APP_ID = "1:134284945450:android:8d07581fa1cb30479b7b53"
FCM_API_KEY = "AIzaSyBx4yHZotCGRs-lDHa8d1RB3fGM4ProsRE"
FCM_PROJECT_ID = "aqualisa-smart-showers-93922"

CONF_REGION = "region"
CONF_MFA_TOKEN = "mfa_token"
CONF_MFA_TYPE = "mfa_type"

REGION_UK = "uk"
REGION_EU = "eu"

FLOW_MIN = 0
FLOW_MED = 1
FLOW_MAX = 2
FLOW_NAMES = {FLOW_MIN: "Min", FLOW_MED: "Med", FLOW_MAX: "Max"}
FLOW_NAME_TO_VALUE = {"Min": FLOW_MIN, "Med": FLOW_MED, "Max": FLOW_MAX}

TEMP_MIN = 15
TEMP_MAX = 55
TEMP_DEFAULT = 38

DURATION_DEFAULT = 600

# FCM push message keys
KEY_LIVE_ON_OFF = "live_on_off"
KEY_LIVE_TEMPERATURE = "live_temperature"
KEY_LIVE_AT_TEMPERATURE = "live_at_temperature"
KEY_LIVE_FLOW = "live_flow"
KEY_LIVE_OUTLET = "live_outlet"
KEY_LIVE_TIMER = "live_timer"
KEY_LIVE_TIME_RUN = "live_time_run"
KEY_REQUEST_ON_OFF = "request_on_off"
KEY_REQUEST_TEMPERATURE = "request_temperature"
KEY_REQUEST_FLOW = "request_flow"
KEY_REQUEST_OUTLET = "request_outlet"
KEY_REQUEST_TIMER = "request_timer"
KEY_USAGE_RUN_TIME = "usage_run_time"
KEY_USAGE_AVG_TEMP = "usage_average_temperature"
KEY_APPLIANCES_ID = "appliancesId"
KEY_TIMESTAMP = "timestamp"
