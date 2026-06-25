"""Starlette request parsing helpers for OAuth HTTP endpoints.

HTTP routes use this module to extract JSON, query, and form data into typed
``oauth.core`` input models before calling service-layer operations.
"""

from collections.abc import Mapping

from authlib.oauth2.rfc6749.errors import InvalidRequestError
from starlette.datastructures import FormData, QueryParams
from starlette.requests import Request

from ..core.requests import (
    AuthorizationRequestInput,
    RegistrationRequest,
    TokenRequestInput,
)

_AUTHORIZATION_KNOWN_KEYS = frozenset(
    {
        "response_type",
        "client_id",
        "redirect_uri",
        "resource",
        "scope",
        "state",
        "code_challenge",
        "code_challenge_method",
    }
)


def _string_items(values: Mapping[str, object]) -> dict[str, str]:
    """Return request values as strings, matching Starlette form/query behavior."""
    return {key: str(value) for key, value in values.items()}


def authorization_input_from_mapping(
    values: Mapping[str, object], *, exclude_pin: bool = False
) -> AuthorizationRequestInput:
    """Parse authorization query or form data into a typed service input."""
    data = _string_items(values)
    if exclude_pin:
        data.pop("pin", None)
    extra_params = {
        key: value
        for key, value in data.items()
        if key not in _AUTHORIZATION_KNOWN_KEYS
    }
    return AuthorizationRequestInput(
        response_type=data.get("response_type"),
        client_id=data.get("client_id"),
        redirect_uri=data.get("redirect_uri"),
        resource=data.get("resource"),
        scope=data.get("scope"),
        state=data.get("state"),
        code_challenge=data.get("code_challenge"),
        code_challenge_method=data.get("code_challenge_method"),
        extra_params=extra_params,
    )


def parse_authorization_query(request: Request) -> AuthorizationRequestInput:
    """Parse an authorization GET request into a typed service input."""
    return authorization_input_from_mapping(request.query_params)


async def parse_authorization_form(
    request: Request,
) -> tuple[AuthorizationRequestInput, str]:
    """Parse an authorization approval form and return typed input plus PIN."""
    form = await request.form()
    return authorization_input_from_mapping(form, exclude_pin=True), str(
        form.get("pin") or ""
    )


async def parse_registration_request(request: Request) -> RegistrationRequest:
    """Parse dynamic client registration JSON into a typed service input."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise InvalidRequestError(
            description="Registration payload must be a JSON object"
        )

    raw_redirect_uris = body.get("redirect_uris")
    if not isinstance(raw_redirect_uris, list):
        raise InvalidRequestError(
            description="redirect_uris must be a non-empty list"
        )
    redirect_uris = tuple(
        value.strip()
        for value in raw_redirect_uris
        if isinstance(value, str) and value.strip()
    )
    if len(redirect_uris) != len(raw_redirect_uris) or not redirect_uris:
        raise InvalidRequestError(
            description="redirect_uris must contain non-empty strings"
        )

    raw_client_name = body.get("client_name")
    client_name = raw_client_name if isinstance(raw_client_name, str) else None
    return RegistrationRequest(
        redirect_uris=redirect_uris,
        client_name=client_name,
    )


async def parse_token_request(request: Request) -> TokenRequestInput:
    """Parse a token endpoint form request into a typed service input."""
    form = await request.form()
    return _token_input_from_form(form)


def _token_input_from_form(form: FormData | QueryParams) -> TokenRequestInput:
    """Convert token endpoint form/query values into a typed service input."""
    data = _string_items(form)
    return TokenRequestInput(
        grant_type=data.get("grant_type"),
        code=data.get("code"),
        client_id=data.get("client_id"),
        redirect_uri=data.get("redirect_uri"),
        resource=data.get("resource"),
        code_verifier=data.get("code_verifier"),
    )
