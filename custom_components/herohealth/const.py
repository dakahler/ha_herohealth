"""Constants for the Hero Health integration."""

DOMAIN = "herohealth"

BASE_URL = "https://cloud.herohealth.com"

# OAuth2 settings (mobile app's public client on id.herohealth.com)
OAUTH_LOGIN_URL = "https://id.herohealth.com/login/"
OAUTH_TOKEN_URL = "https://id.herohealth.com/o/token/"
OAUTH_CLIENT_ID = "sGNw0O6padHYWwSWIon21jt1QqEYAkmZLYUps60L"
OAUTH_REDIRECT_URI = "heroapp://auth"

HERO_CLIENT_HEADER = "HeroWeb;desktop-Chrome;4.0.0"

# 5 minutes - medication events are time-sensitive
DEFAULT_SCAN_INTERVAL = 300

# Token lifetime is 900s (15 min); refresh proactively with 2 min buffer
TOKEN_LIFETIME_SECONDS = 900

CONF_REFRESH_TOKEN = "refresh_token"
