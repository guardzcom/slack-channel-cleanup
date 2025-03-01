from enum import Enum
from typing import Optional, Dict
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

class ChannelAction(str, Enum):
    """Supported actions for channel management."""
    KEEP = "keep"
    ARCHIVE = "archive"
    RENAME = "rename"
    
    @classmethod
    def values(cls) -> list[str]:
        return [action.value for action in cls]

class ChannelActionResult:
    """Result of a channel action execution."""
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message

class ChannelActionHandler:
    def __init__(self, client: WebClient):
        self.client = client
    
    async def execute_action(
        self,
        channel_id: str,
        channel_name: str,
        action: str,
        target_value: Optional[str] = None
    ) -> ChannelActionResult:
        """
        Execute the specified action on a channel.
        
        Args:
            channel_id: The Slack channel ID
            channel_name: The current channel name
            action: The action to perform (from ChannelAction)
            target_value: Additional value needed for archive (target channel for redirect) or rename (new name)
        """
        try:
            if action in [ChannelAction.KEEP]:
                return ChannelActionResult(True, f"Channel {channel_name} kept as is")
                
            elif action == ChannelAction.ARCHIVE:
                response = await self.archive_channel(channel_id, channel_name, target_value)
                return response
                
            elif action == ChannelAction.RENAME:
                if not target_value:
                    return ChannelActionResult(False, f"New name not specified for renaming {channel_name}")
                response = await self.rename_channel(channel_id, channel_name, target_value)
                return response
                
            else:
                return ChannelActionResult(False, f"Unknown action '{action}' for channel {channel_name}")
                
        except SlackApiError as e:
            error = e.response["error"]
            return ChannelActionResult(False, f"Slack API error for {channel_name}: {error}")
        except Exception as e:
            return ChannelActionResult(False, f"Unexpected error for {channel_name}: {str(e)}")
    
    async def archive_channel(self, channel_id: str, channel_name: str, target_channel: Optional[str] = None) -> ChannelActionResult:
        """
        Archive a channel. If target_channel is provided, post a redirect notice before archiving.
        
        Args:
            channel_id: The channel ID to archive
            channel_name: The name of the channel to archive
            target_channel: Optional target channel name for redirect notice
        """
        try:
            # First check channel info and status
            try:
                channel_info = self.client.conversations_info(channel=channel_id)["channel"]
                
                # Check if already archived
                if channel_info.get("is_archived", False):
                    return ChannelActionResult(
                        False,
                        f"#{channel_name} is already archived"
                    )
                
                # Check if it's the general channel
                if channel_info.get("is_general"):
                    return ChannelActionResult(
                        False,
                        f"Cannot archive #{channel_name}: This is the workspace's general channel"
                    )
            except SlackApiError as e:
                if e.response["error"] == "channel_not_found":
                    return ChannelActionResult(
                        False,
                        f"Cannot archive #{channel_name}: Channel not found"
                    )
                raise

            # If target channel specified, handle redirect notice
            if target_channel:
                target_channel = target_channel.lstrip('#')
                try:
                    # Verify target channel exists and is not archived
                    channels = self.client.conversations_list(
                        types="public_channel,private_channel",
                        limit=200
                    )["channels"]
                    target = next((ch for ch in channels if ch["name"] == target_channel), None)
                    
                    if not target:
                        return ChannelActionResult(
                            False,
                            f"Cannot archive #{channel_name}: Target channel #{target_channel} does not exist"
                        )
                    
                    if target.get("is_archived", False):
                        return ChannelActionResult(
                            False,
                            f"Cannot archive #{channel_name}: Target channel #{target_channel} is archived"
                        )
                    
                    # Get the target channel ID for proper mention
                    target_id = target["id"]
                    
                    # Try to post redirect notice
                    message = (
                        f"🔄 *Channel Redirect Notice*\n"
                        f"This channel is being archived. Please join <#{target_id}> to continue the discussion."
                    )
                    
                    try:
                        # Try to join the channel first if we're not already a member
                        try:
                            self.client.conversations_join(channel=channel_id)
                        except SlackApiError:
                            pass  # Ignore if we can't join or are already a member
                        
                        # Try to post the message
                        self.client.chat_postMessage(
                            channel=channel_id,
                            text=message,
                            mrkdwn=True
                        )
                    except SlackApiError as e:
                        if e.response["error"] == "not_in_channel":
                            return ChannelActionResult(
                                False,
                                f"Cannot archive #{channel_name}: Unable to post redirect notice (not in channel)"
                            )
                        # Continue with archive even if we couldn't post the message for other reasons
                        pass
                    
                except SlackApiError:
                    return ChannelActionResult(
                        False,
                        f"Cannot archive #{channel_name}: Failed to verify target channel"
                    )
                
            # Archive the channel
            response = self.client.conversations_archive(channel=channel_id)
            
            if response["ok"]:
                message = f"Successfully archived #{channel_name}"
                if target_channel:
                    message += f" (with redirect to #{target_channel})"
                return ChannelActionResult(True, message)
                
        except SlackApiError as e:
            error = e.response["error"]
            error_messages = {
                "already_archived": f"#{channel_name} is already archived",
                "cant_archive_general": f"Cannot archive #{channel_name}: This is the workspace's general channel",
                "cant_archive_required": f"Cannot archive #{channel_name}: This is a required channel",
                "not_in_channel": f"Cannot archive #{channel_name}: You must be a member of the channel",
                "restricted_action": f"Cannot archive #{channel_name}: Your workspace settings prevent channel archiving",
                "missing_scope": (
                    f"Cannot archive #{channel_name}: Missing required permissions. "
                    "Need channels:write for public channels or groups:write for private channels."
                )
            }
            return ChannelActionResult(
                False, 
                error_messages.get(error, f"Failed to archive #{channel_name}: {error}")
            )
    
    async def rename_channel(
        self,
        channel_id: str,
        old_name: str,
        new_name: str
    ) -> ChannelActionResult:
        """Rename a channel."""
        # Validate new name
        if not new_name:
            return ChannelActionResult(
                False,
                f"Cannot rename {old_name}: New name cannot be empty"
            )
        
        if len(new_name) > 80:
            return ChannelActionResult(
                False,
                f"Cannot rename {old_name}: New name exceeds 80 characters"
            )
        
        # Check for valid characters (lowercase letters, numbers, hyphens, underscores)
        if not all(c.islower() or c.isdigit() or c in '-_' for c in new_name) or '.' in new_name:
            return ChannelActionResult(
                False,
                f"Cannot rename {old_name}: Channel names can only contain lowercase letters, "
                "numbers, hyphens, and underscores"
            )
        
        try:
            response = self.client.conversations_rename(
                channel=channel_id,
                name=new_name
            )
            
            if response["ok"]:
                # Store the actual name returned by Slack as it might be modified
                actual_name = response["channel"]["name"]
                if actual_name != new_name:
                    return ChannelActionResult(
                        True,
                        f"Successfully renamed {old_name} to {actual_name} "
                        "(name was modified to meet Slack's requirements)"
                    )
                return ChannelActionResult(
                    True,
                    f"Successfully renamed {old_name} to {new_name}"
                )
                
        except SlackApiError as e:
            error = e.response["error"]
            error_messages = {
                "not_authorized": "You don't have permission to rename this channel. "
                                "Only channel creators, workspace admins, or channel managers can rename channels.",
                "name_taken": f"Cannot rename {old_name}: The name '{new_name}' is already taken",
                "invalid_name": f"Cannot rename {old_name}: Invalid channel name format",
                "not_in_channel": f"Cannot rename {old_name}: You must be a member of the channel",
                "is_archived": f"Cannot rename {old_name}: Channel is archived"
            }
            return ChannelActionResult(False, error_messages.get(error, f"Failed to rename {old_name}: {error}")) 