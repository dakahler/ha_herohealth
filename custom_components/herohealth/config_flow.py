"""Config flow for Hero Health integration.

Authenticates via the same OAuth2 flow as the mobile app:
1. GET id.herohealth.com/login/ with OAuth + PKCE params → login form + CSRF token
2. POST email + password → redirect with authorization code
3. Exchange code for tokens at /o/token/
4. Use tokens to access cloud.herohealth.com API
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HeroHealthApiClient, HeroHealthAuthError
from .const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    OAUTH_CLIENT_ID,
    OAUTH_LOGIN_URL,
    OAUTH_REDIRECT_URI,
    OAUTH_TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HeroHealthConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hero Health."""

    VERSION = 1

    async def _authenticate(
        self, email: str, password: str
    ) -> dict[str, Any]:
        """Perform the full OAuth2 login flow programmatically.

        Returns the token response dict with access_token and refresh_token.
        """
        session = async_get_clientsession(self.hass)

        # Generate PKCE challenge
        verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
        nonce = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()

        oauth_params = {
            "redirect_uri": OAUTH_REDIRECT_URI,
            "client_id": OAUTH_CLIENT_ID,
            "response_type": "code",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        login_page_url = f"{OAUTH_LOGIN_URL}?{urlencode(oauth_params)}"

        # Step 1: GET login page to obtain CSRF token and session cookie
        jar = aiohttp.CookieJar(unsafe=True)
        temp_session = aiohttp.ClientSession(cookie_jar=jar)
        try:
            async with temp_session.get(login_page_url) as resp:
                if resp.status != 200:
                    raise HeroHealthAuthError(
                        f"Login page returned {resp.status}"
                    )
                html = await resp.text()

            # Extract CSRF token from form
            csrf_match = re.search(
                r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)',
                html,
            )
            if not csrf_match:
                _LOGGER.error("No CSRF token found in login page")
                raise HeroHealthAuthError("Login page format unexpected")
            csrf_token = csrf_match.group(1)

            # Extract form action URL (contains user_state parameter)
            action_match = re.search(
                r'<form[^>]*action=["\']([^"\']*)', html, re.IGNORECASE
            )
            form_action = action_match.group(1) if action_match else "/login/"
            if form_action.startswith("/"):
                post_url = f"https://id.herohealth.com{form_action}"
            else:
                post_url = form_action

            # Get CSRF cookie
            csrf_cookie = None
            for cookie in jar:
                if cookie.key == "csrftoken":
                    csrf_cookie = cookie.value

            # Step 2: POST login credentials
            form_data = {
                "csrfmiddlewaretoken": csrf_token,
                "email": email,
                "password": password,
                "visitor_id": "",
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_page_url,
                "Origin": "https://id.herohealth.com",
            }
            if csrf_cookie:
                headers["X-CSRFToken"] = csrf_cookie

            async with temp_session.post(
                post_url,
                data=form_data,
                headers=headers,
                allow_redirects=False,
            ) as resp:
                location = resp.headers.get("Location", "")
                _LOGGER.debug("Login POST status=%s location=%s", resp.status, location[:100])

                if resp.status == 401:
                    raise HeroHealthAuthError("Invalid email or password")
                if resp.status != 302 or "code=" not in location:
                    raise HeroHealthAuthError(
                        f"Login failed: status {resp.status}"
                    )

            # Extract authorization code from redirect
            parsed = urlparse(location)
            query_params = parse_qs(parsed.query)
            code = query_params.get("code", [None])[0]
            if not code:
                raise HeroHealthAuthError("No authorization code in redirect")

            # Step 3: Exchange code for tokens
            exchange_data = {
                "grant_type": "authorization_code",
                "client_id": OAUTH_CLIENT_ID,
                "code": code,
                "redirect_uri": OAUTH_REDIRECT_URI,
                "code_verifier": verifier,
            }
            async with temp_session.post(
                OAUTH_TOKEN_URL,
                data=exchange_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    result = await resp.json(content_type=None)
                    error = result.get("error", "unknown") if isinstance(result, dict) else str(result)
                    raise HeroHealthAuthError(f"Token exchange failed: {error}")
                return await resp.json(content_type=None)
        finally:
            await temp_session.close()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — email + password login."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            try:
                tokens = await self._authenticate(email, password)
            except HeroHealthAuthError as err:
                _LOGGER.debug("Authentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during authentication")
                errors["base"] = "unknown"
            else:
                access_token = tokens.get("access_token", "")
                refresh_token = tokens.get("refresh_token", "")

                if not access_token or not refresh_token:
                    errors["base"] = "invalid_auth"
                else:
                    # Fetch user details for account_id
                    try:
                        session = async_get_clientsession(self.hass)
                        client = HeroHealthApiClient(
                            session=session,
                            refresh_token=refresh_token,
                        )
                        client._access_token = access_token
                        client._token_acquired_at = time.monotonic()
                        user_details = await client.get_user_details()
                    except Exception:
                        _LOGGER.exception("Failed to get user details")
                        user_details = {}

                    account_id = (
                        user_details.get("account_id")
                        or user_details.get("id")
                        or user_details.get("user_id")
                        or ""
                    )

                    await self.async_set_unique_id(email.lower())
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=email,
                        data={
                            CONF_EMAIL: email,
                            CONF_REFRESH_TOKEN: refresh_token,
                            CONF_ACCOUNT_ID: str(account_id),
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
