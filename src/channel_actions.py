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
        response = self.client.conversations_archive(channel=channel_id)
        if response["ok"]:
            return ChannelActionResult(True, f"Successfully archived channel {channel_name}")
        return ChannelActionResult(False, f"Failed to archive channel {channel_name}")
    
    async def merge_channel(
        self,
        channel_id: str,
        channel_name: str,
        target_channel: str
    ) -> ChannelActionResult:
        """Merge a channel by posting a message and archiving it."""
        # Remove '#' prefix if present in target channel
        target_channel = target_channel.lstrip('#')
        
        # Post message about the merge
        message = f"🔄 This channel is being merged into #{target_channel}. Please join that channel to continue the discussion."
        try:
            self.client.chat_postMessage(
                channel=channel_id,
                text=message,
                parse="full"
            )
        except SlackApiError as e:
            return ChannelActionResult(False, f"Failed to post merge message in {channel_name}: {e.response['error']}")
        
        # Archive the channel
        return await self.archive_channel(channel_id, channel_name)
    
    async def rename_channel(
        self,
        channel_id: str,
        old_name: str,
        new_name: str
    ) -> ChannelActionResult:
        """Rename a channel."""
        # Validate new name
        if not new_name.islower() or ' ' in new_name or '.' in new_name:
            return ChannelActionResult(
                False,
                f"Invalid new name '{new_name}' for {old_name}. Names must be lowercase, without spaces/periods."
            )
        
        response = self.client.conversations_rename(
            channel=channel_id,
            name=new_name
        )
        
        if response["ok"]:
            return ChannelActionResult(True, f"Successfully renamed channel {old_name} to {new_name}")
        return ChannelActionResult(False, f"Failed to rename channel {old_name}") 