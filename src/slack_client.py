import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def validate_token_type(client: WebClient) -> None:
    """
    Validate that we're using a user token (xoxp) and not a bot token (xoxb).
    Raises ValueError if the token is not a user token.
    """
    try:
        # auth.test will return information about the token
        response = client.auth_test()
        token_type = response.get("token_type")
        
        if "user" not in str(token_type).lower():
            raise ValueError(
                "Invalid token type. Please use a user token (xoxp) instead of a bot token. "
                "User tokens are required for channel management operations."
            )
    except SlackApiError as e:
        raise ValueError(f"Failed to validate token: {str(e)}")

def validate_scopes(client: WebClient) -> None:
    """
    Validate that the token has the required scopes for channel management.
    Required scopes: channels:write (public channels), groups:write (private channels)
    Raises ValueError if required scopes are missing.
    """
    try:
        response = client.auth_test()
        scopes = response.get("scope", "").split(",")
        
        required_scopes = {"channels:write", "groups:write"}
        missing_scopes = required_scopes - set(scopes)
        
        if missing_scopes:
            raise ValueError(
                f"Missing required scopes: {', '.join(missing_scopes)}. "
                "Please add these scopes to your Slack app configuration."
            )
    except SlackApiError as e:
        raise ValueError(f"Failed to validate scopes: {str(e)}")

def get_slack_client() -> WebClient:
    """
    Create and return a Slack WebClient instance with validated token and scopes.
    
    Required Token Type:
    - User token (xoxp) is required, bot tokens are not supported
    
    Required Scopes:
    - channels:write: For renaming public channels
    - groups:write: For renaming private channels
    
    Returns:
        WebClient: Configured Slack client
    
    Raises:
        ValueError: If token is missing, invalid, or has insufficient permissions
    """
    load_dotenv()
    token = os.getenv("SLACK_TOKEN")
    
    if not token:
        raise ValueError("SLACK_TOKEN environment variable is not set")
    
    if not token.startswith("xoxp-"):
        raise ValueError(
            "Invalid token format. Token must be a user token (starts with 'xoxp-'). "
            "Bot tokens are not supported for channel management operations."
        )
    
    client = WebClient(token=token)
    
    # Validate token type and scopes
    validate_token_type(client)
    validate_scopes(client)
    
    return client 