from enum import Enum
from typing import Optional, Dict
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

class ChannelAction(str, Enum):
    """Supported actions for channel management."""
    KEEP = "keep"
    ARCHIVE = "archive"
    MERGE = "merge"
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
            target_value: Additional value needed for merge (target channel) or rename (new name)
        """
        try:
            if action == ChannelAction.KEEP:
                return ChannelActionResult(True, f"Channel {channel_name} kept as is")
                
            elif action == ChannelAction.ARCHIVE:
                response = await self.archive_channel(channel_id, channel_name)
                return response
                
            elif action == ChannelAction.MERGE:
                if not target_value:
                    return ChannelActionResult(False, f"Target channel not specified for merging {channel_name}")
                response = await self.merge_channel(channel_id, channel_name, target_value)
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
    
    async def archive_channel(self, channel_id: str, channel_name: str) -> ChannelActionResult:
        """Archive a channel."""
        try:
            # First check if it's the general channel
            channel_info = self.client.conversations_info(channel=channel_id)["channel"]
            if channel_info.get("is_general"):
                return ChannelActionResult(
                    False,
                    f"Cannot archive #{channel_name}: This is the workspace's general channel"
                )
                
            response = self.client.conversations_archive(channel=channel_id)
            
            if response["ok"]:
                return ChannelActionResult(
                    True,
                    f"Successfully archived #{channel_name}"
                )
                
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
    
    async def merge_channel(
        self,
        channel_id: str,
        channel_name: str,
        target_channel: str
    ) -> ChannelActionResult:
        """Merge a channel by posting a message and archiving it."""
        # Remove '#' prefix if present in target channel
        target_channel = target_channel.lstrip('#')
        
        try:
            # First verify the target channel exists
            try:
                channels = self.client.conversations_list(
                    types="public_channel,private_channel",
                    limit=200
                )["channels"]
                target = next((ch for ch in channels if ch["name"] == target_channel), None)
                if not target:
                    return ChannelActionResult(
                        False,
                        f"Cannot merge #{channel_name}: Target channel #{target_channel} does not exist"
                    )
                    
                # Get the target channel ID for proper mention
                target_id = target["id"]
            except SlackApiError:
                # If we can't verify the target channel, we'll still try to post the message
                target_id = None
            
            # Post message about the merge
            message = (
                f"🔄 *Channel Merge Notice*\n"
                f"This channel is being merged into <#{target_id or target_channel}>.\n"
                f"Please join that channel to continue the discussion."
            )
            
            try:
                self.client.chat_postMessage(
                    channel=channel_id,
                    text=message,
                    mrkdwn=True  # Enable markdown formatting for the channel mention
                )
            except SlackApiError as e:
                error = e.response["error"]
                error_messages = {
                    "channel_not_found": f"Cannot merge #{channel_name}: Channel not found",
                    "not_in_channel": f"Cannot merge #{channel_name}: Bot must be invited to the channel first",
                    "is_archived": f"Cannot merge #{channel_name}: Channel is already archived",
                    "restricted_action": f"Cannot merge #{channel_name}: Workspace settings prevent posting messages",
                    "missing_scope": (
                        f"Cannot merge #{channel_name}: Missing required permissions. "
                        "Need chat:write scope for posting messages."
                    )
                }
                return ChannelActionResult(
                    False,
                    error_messages.get(error, f"Failed to post merge message in #{channel_name}: {error}")
                )
            
            # Archive the channel
            return await self.archive_channel(channel_id, channel_name)
            
        except Exception as e:
            return ChannelActionResult(
                False,
                f"Unexpected error while merging #{channel_name}: {str(e)}"
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
        if not all(c.islower() or c.isdigit() or c in '-_' for c in new_name):
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