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

# Token assumed lifetime (50 minutes, conservative for typical 60-min tokens)
TOKEN_LIFETIME_SECONDS = 3000

CONF_ACCOUNT_ID = "account_id"
CONF_REFRESH_TOKEN = "refresh_token"
