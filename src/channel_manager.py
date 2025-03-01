import os
import asyncio
import json
import time
from typing import List, Dict, Optional
from slack_sdk.errors import SlackApiError
from .slack_client import get_slack_client
from .channel_data import (
    read_channels_from_csv,
    create_csv_writer,
    write_channel_to_csv
)
from .sheet_manager import SheetManager
from .channel_actions import ChannelActionHandler, ChannelAction

# Cache file path (in project directory)
CACHE_FILE = "channel_activity_cache.json"
# Cache expiration in seconds (24 hours)
CACHE_EXPIRATION = 86400

async def fetch_channel_history(client, channel: Dict) -> None:
    """Fetch history for a single channel."""

    channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
    
    try:
        # Add retry logic for rate limits
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                history = client.conversations_history(
                    channel=channel["id"],
                    limit=20,  # Fetch more messages to ensure we get at least one actual message
                    include_all_metadata=False  # We only need the timestamp
                )
                
                # Filter for actual messages (not system messages)
                messages = [msg for msg in history.get("messages", []) 
                           if not msg.get("subtype")]
                if messages:
                    # messages are already sorted by timestamp (newest first)
                    channel["latest"] = messages[0]
                return
                
            except SlackApiError as e:
                if e.response.get("error") == "rate_limited":
                    retry_count += 1
                    retry_after = int(e.response.get("headers", {}).get("Retry-After", 5))
                    print(f"    ⚠️  Rate limited when fetching history for #{channel_name}, waiting {retry_after}s (retry {retry_count}/{max_retries})")
                    await asyncio.sleep(retry_after)
                else:
                    # For non-rate limit errors, raise to outer exception handler
                    raise
                    
        # If we've exhausted retries
        if retry_count >= max_retries:
            print(f"    ⚠️  Failed to fetch history for #{channel_name} after {max_retries} retries")
            
    except SlackApiError as e:
        print(f"    ⚠️  Could not fetch history for #{channel_name}: {e.response.get('error', 'unknown error')}")
    except Exception as e:
        print(f"    ⚠️  Error fetching history for #{channel_name}: {str(e)}")

def load_cache() -> Dict:
    """Load channel activity data from cache file if it exists and is not expired."""
    if not os.path.exists(CACHE_FILE):
        return {}
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache = json.load(f)
        
        # Check if cache is expired
        if time.time() - cache.get('timestamp', 0) > CACHE_EXPIRATION:
            print("Cache is expired, will fetch fresh data")
            return {}
        
        return cache
    except Exception as e:
        print(f"Warning: Could not load cache: {str(e)}")
        return {}

def save_cache(channels: List[Dict]) -> None:
    """Save channel activity data to cache file."""
    try:
        # Extract only the channel ID and last activity data
        activity_data = {}
        for channel in channels:
            try:
                if channel.get("latest") and channel.get("id"):
                    activity_data[channel["id"]] = {
                        "ts": channel["latest"].get("ts"),
                        "text": channel["latest"].get("text", "")[:50]  # Store truncated message text for reference
                    }
            except Exception:
                # Skip this channel if there's any issue
                continue
        
        cache = {
            'timestamp': time.time(),
            'activity': activity_data
        }
        
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache, f)
        
        print(f"Cached activity data for {len(activity_data)} channels to {CACHE_FILE}")
    except Exception as e:
        print(f"Warning: Could not save cache: {str(e)}")

def apply_cached_activity(channels: List[Dict], cache: Dict) -> None:
    """Apply cached activity data to channel list."""
    if not cache or 'activity' not in cache:
        return
    
    activity_data = cache['activity']
    applied_count = 0
    
    for channel in channels:
        # Make sure channel has an id before trying to access it
        if channel.get("id") and channel["id"] in activity_data:
            try:
                # Create a minimal "latest" structure with just the timestamp
                channel["latest"] = {"ts": activity_data[channel["id"]]["ts"]}
                applied_count += 1
            except (KeyError, TypeError):
                # Skip if there's any issue with the cached data
                continue
    
    if applied_count > 0:
        print(f"Applied cached activity data to {applied_count} channels")

async def get_all_channels(csv_writer=None, use_cache: bool = True, force_refresh: bool = False, dry_run: bool = False) -> List[Dict]:
    """
    Fetch all active channels (public and private) from Slack workspace.
    Returns a list of channel dictionaries.
    
    Args:
        csv_writer: Optional CSV writer to write channels as they're fetched
        use_cache: Whether to use cached data if available
        force_refresh: Whether to force a refresh of the data
        dry_run: Whether this is a dry run (won't save cache)
    """
    client = get_slack_client()
    channels = []
    cursor = None
    page = 1
    rate_limit_count = 0
    
    # Load cache if not forcing refresh
    cache = {}
    if use_cache and not force_refresh:
        try:
            cache = load_cache()
        except Exception as e:
            print(f"Warning: Could not load cache: {str(e)}")
            cache = {}
    
    print("\nFetching channels (200 per page)...")
    while True:
        try:
            print(f"Fetching page {page}...")
            response = client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
                include_num_members=True
            )
            
            if not response["ok"]:
                raise SlackApiError("Failed to fetch channels", response)
            
            new_channels = response["channels"]
            
            # Safety check: validate channel data before adding
            for channel in new_channels:
                if not channel.get("id"):
                    print(f"⚠️  Warning: Skipping channel with missing ID")
                    continue
                if not channel.get("name"):
                    print(f"⚠️  Warning: Skipping channel with ID {channel.get('id')} - missing name")
                    continue
                channels.append(channel)
            
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
            
            page += 1
            await asyncio.sleep(0.5)  # Increased delay between pages to avoid rate limits
            
        except SlackApiError as e:
            error_code = e.response.get("error", "unknown_error")
            if error_code == "rate_limited":
                rate_limit_count += 1
                if rate_limit_count > 3:
                    print("Too many rate limit errors, aborting")
                    raise
                retry_after = int(e.response.get("headers", {}).get("Retry-After", 10))
                print(f"Rate limited. Waiting {retry_after} seconds...")
                await asyncio.sleep(retry_after)
                continue
            elif error_code in ["missing_scope", "invalid_auth"]:
                raise ValueError(
                    "Missing required scopes or invalid authentication. "
                    "Ensure your token has channels:read and groups:read scopes."
                )
            raise
    
    print(f"\nFetched {len(channels)} total channels")
    
    # Apply cached activity data if available
    if use_cache and not force_refresh and cache:
        apply_cached_activity(channels, cache)
        
        # Only fetch activity for channels without cached data
        channels_to_update = [ch for ch in channels if not ch.get("latest")]
        if channels_to_update:
            print(f"\nFetching last activity for {len(channels_to_update)} channels without cached data...")
            
            # Create tasks for concurrent history fetching
            tasks = []
            for i, channel in enumerate(channels_to_update, 1):
                try:
                    channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
                    print(f"  Queuing #{channel_name}...")
                    tasks.append(fetch_channel_history(client, channel))
                    if len(tasks) >= 10:  # Process in batches of 10
                        await asyncio.gather(*tasks)
                        tasks = []
                        await asyncio.sleep(0.2)  # Small delay between batches
                except Exception as e:
                    print(f"  ⚠️  Error queuing channel: {str(e)}")
                    continue
            
            # Process any remaining tasks
            if tasks:
                await asyncio.gather(*tasks)
        else:
            print("\nUsing cached activity data for all channels")
    else:
        # Fetch activity for all channels
        print(f"\nFetching last activity for {len(channels)} channels...")
        
        # Create tasks for concurrent history fetching
        tasks = []
        for i, channel in enumerate(channels, 1):
            try:
                channel_name = channel.get('name', channel.get('id', 'UNKNOWN'))
                print(f"  Queuing #{channel_name}...")
                tasks.append(fetch_channel_history(client, channel))
                if len(tasks) >= 10:  # Process in batches of 10
                    await asyncio.gather(*tasks)
                    tasks = []
                    await asyncio.sleep(0.2)  # Small delay between batches
            except Exception as e:
                print(f"  ⚠️  Error queuing channel: {str(e)}")
                continue
        
        # Process any remaining tasks
        if tasks:
            await asyncio.gather(*tasks)
    
    # Write to CSV if writer provided
    if csv_writer:
        for channel in channels:
            write_channel_to_csv(csv_writer, channel)
    
    # Save activity data to cache (skip if dry run)
    if not dry_run:
        save_cache(channels)
    
    return channels

async def get_channel_info(client, channel_id: str) -> Dict:
    """Get detailed channel information."""
    try:
        response = client.conversations_info(
            channel=channel_id,
            include_num_members=True  # Request member count in response
        )
        return response["channel"]
    except SlackApiError:
        return {}

async def get_user_approval(client, channel: Dict, action: str, target_value: Optional[str] = None, current_channels: Optional[List[Dict]] = None) -> bool:
    """
    Get user approval for an action.
    
    Args:
        client: Slack client
        channel: Channel dictionary
        action: Action to perform
        target_value: Target value for rename action or target channel for archive
        current_channels: Optional list of current channels to validate against
    """
    action_desc = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: target_value and f"archive (with notice to join #{target_value})" or "archive",
        ChannelAction.RENAME.value: f"rename to '{target_value}'"
    }
    
    desc = action_desc.get(action, action)
    channel_name = f"#{channel['name']}"
    if channel.get("is_private"):
        channel_name = f"🔒 {channel_name}"
    
    # Get detailed channel info
    channel_info = await get_channel_info(client, channel["channel_id"])
    
    print("\n" + "=" * 80)
    print(f"Channel: {channel_name}")
    print(f"Members: {channel_info.get('num_members', 'unknown')}")
    print(f"Created: {channel.get('created_date', 'unknown')}")
    if channel_info.get("purpose", {}).get("value"):
        print(f"Purpose: {channel_info['purpose']['value']}")
    if channel_info.get("topic", {}).get("value"):
        print(f"Topic: {channel_info['topic']['value']}")
    
    # Show last activity if available
    if channel_info.get("last_read"):
        try:
            from datetime import datetime
            last_read = datetime.fromtimestamp(float(channel_info["last_read"]))
            # Skip if date is Unix epoch (indicates no activity)
            if last_read.year > 1970:
                print(f"Last Activity: {last_read.strftime('%Y-%m-%d')}")
            else:
                print("Last Activity: No activity recorded")
        except ValueError:
            print("Last Activity: Unable to parse timestamp")
    
    print(f"\nProposed Action: {desc}")
    
    # For archive actions with target channel, show target channel info
    if action == ChannelAction.ARCHIVE.value and target_value:
        try:
            # Get target channel info by name from current_channels if available
            target = None
            target_name = target_value.lstrip('#')
            
            if current_channels:
                target = next((ch for ch in current_channels if ch["name"] == target_name), None)
            else:
                # Fallback to API call if current_channels not provided
                target_channels = client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True
                )["channels"]
                target = next((ch for ch in target_channels if ch["name"] == target_name), None)
            
            if target:
                # Now get detailed info using the correct channel ID
                target_info = await get_channel_info(client, target["id"])
                print("\nTarget Channel Information:")
                print(f"Members: {target_info.get('num_members', 'unknown')}")
                if target_info.get("purpose", {}).get("value"):
                    print(f"Purpose: {target_info['purpose']['value']}")
                if target_info.get("topic", {}).get("value"):
                    print(f"Topic: {target_info['topic']['value']}")
                    
                # Warn about redirecting to a smaller channel
                source_members = int(channel.get("num_members", 0))
                target_members = int(target_info.get('num_members', 0))
                if target_members < source_members:
                    print("\n⚠️  Warning: Target channel has fewer members than source channel!")
            else:
                print(f"\n⚠️  Warning: Target channel #{target_value} not found!")
                while True:
                    response = input("\nPress 'r' to try a different target channel, 'n' to skip, or 'q' to quit: ").lower()
                    if response == 'q':
                        raise KeyboardInterrupt("User requested to quit")
                    if response == 'n':
                        return False
                    if response == 'r':
                        new_target = input("\nEnter new target channel name (without #): ").strip().lower()
                        if not new_target:
                            print("Name cannot be empty")
                            continue
                        if ' ' in new_target or '.' in new_target:
                            print("Name cannot contain spaces or periods")
                            continue
                        channel["target_value"] = new_target
                        return await get_user_approval(client, channel, action, new_target, current_channels)
        except SlackApiError:
            print(f"\n⚠️  Warning: Could not fetch target channel information")
            while True:
                response = input("\nPress 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
    
    # For rename actions, validate the new name
    if action == ChannelAction.RENAME.value and target_value:
        # Check length
        if len(target_value) > 80:
            print("\n❌ Error: Channel name is too long!")
            print("Channel names must be 80 characters or less")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
            
        # Check format
        if not target_value.islower() or ' ' in target_value or '.' in target_value:
            print("\n❌ Error: Invalid channel name format!")
            print("Channel names must:")
            print("- Be lowercase")
            print("- Not contain spaces or periods")
            print("- Only use letters, numbers, hyphens, and underscores")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
            
        # Check valid characters
        if not all(c.islower() or c.isdigit() or c in '-_' for c in target_value):
            print("\n❌ Error: Channel name contains invalid characters!")
            print("Only lowercase letters, numbers, hyphens, and underscores are allowed")
            while True:
                response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                if response == 'q':
                    raise KeyboardInterrupt("User requested to quit")
                if response == 'n':
                    return False
                if response == 'r':
                    new_name = input("\nEnter new channel name (without #): ").strip().lower()
                    if not new_name:
                        print("Name cannot be empty")
                        continue
                    channel["target_value"] = new_name
                    return await get_user_approval(client, channel, action, new_name, current_channels)
        
        # Check if name is already taken (using current_channels if available)
        if current_channels:
            if any(ch["name"] == target_value for ch in current_channels):
                print(f"\n❌ Error: Channel name '{target_value}' is already taken!")
                while True:
                    response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                    if response == 'q':
                        raise KeyboardInterrupt("User requested to quit")
                    if response == 'n':
                        return False
                    if response == 'r':
                        new_name = input("\nEnter new channel name (without #): ").strip().lower()
                        if not new_name:
                            print("Name cannot be empty")
                            continue
                        if ' ' in new_name or '.' in new_name:
                            print("Name cannot contain spaces or periods")
                            continue
                        channel["target_value"] = new_name
                        return await get_user_approval(client, channel, action, new_name, current_channels)
        else:
            try:
                existing = client.conversations_list(
                    types="public_channel,private_channel",
                    exclude_archived=True
                )["channels"]
                if any(ch["name"] == target_value for ch in existing):
                    print(f"\n❌ Error: Channel name '{target_value}' is already taken!")
                    while True:
                        response = input("\nPress 'r' to try a different name, 'n' to skip, or 'q' to quit: ").lower()
                        if response == 'q':
                            raise KeyboardInterrupt("User requested to quit")
                        if response == 'n':
                            return False
                        if response == 'r':
                            new_name = input("\nEnter new channel name (without #): ").strip().lower()
                            if not new_name:
                                print("Name cannot be empty")
                                continue
                            if ' ' in new_name or '.' in new_name:
                                print("Name cannot contain spaces or periods")
                                continue
                            channel["target_value"] = new_name
                            return await get_user_approval(client, channel, action, new_name, current_channels)
            except SlackApiError:
                print("\n⚠️  Warning: Could not validate channel name availability")
    
    if channel.get("notes"):
        print(f"\nNotes: {channel['notes']}")
    print("-" * 80)
    
    # Extra warning for destructive actions
    if action == ChannelAction.ARCHIVE.value:
        print("\n⚠️  WARNING: This is a destructive action that cannot be easily undone!")
        print("The channel will be archived and members will need to be manually re-added if restored.")
        if target_value:
            print("Members will need to manually join the target channel.")
    
    while True:
        response = input("\nPress 'y' to approve, 'n' to skip, or 'q' to quit: ").lower()
        if response == 'q':
            raise KeyboardInterrupt("User requested to quit")
        if response in ['y', 'n']:
            return response == 'y'

async def execute_channel_actions(channels: List[Dict], dry_run: bool = False, batch_size: int = 10) -> List[str]:
    """Process pending actions for the specified channels.
    
    Args:
        channels: List of channels to process
        dry_run: Whether to simulate execution without making changes
        batch_size: Number of channels to confirm at once (0 for individual confirmation)
    
    Returns:
        List of channel IDs that were successfully processed
    """
    client = get_slack_client()
    handler = ChannelActionHandler(client)
    
    successful = 0
    failed = 0
    skipped = 0
    last_action = None
    successful_channel_ids = []  # Track successful channels
    
    # Action descriptions for messages
    action_desc = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: "archive",
        ChannelAction.RENAME.value: "rename to"
    }
    
    print("\nExecuting channel actions:")
    print("=" * 80)
    if batch_size > 0:
        print(f"Channels will be processed in batches of {batch_size}")
        print("For each batch, you can:")
        print("- Press 'y' to approve all")
        print("- Press 'n' to skip all")
        print("- Press 'i' to review individually")
        print("- Press 'q' to quit the process")
    else:
        print("For each action, you can:")
        print("- Press 'y' to approve")
        print("- Press 'n' to skip")
        print("- Press 'q' to quit the process")
    
    print("\nNotes:")
    print("- Destructive actions (archive) require additional confirmation")
    print("- Actions are sorted to process renames before archives")
    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made to channels")
    print("=" * 80)
    
    try:
        # Sort channels by action type (renames first, then archives)
        def action_priority(channel):
            action = channel.get("action", "").lower()
            if not action:  # Handle missing action
                return 3
            if action == ChannelAction.KEEP.value:
                return 2
            elif action == ChannelAction.RENAME.value:
                return 0
            elif action == ChannelAction.ARCHIVE.value:
                return 1
            return 3
        
        channels = sorted(channels, key=action_priority)
        
        # Get current channels once for validation (use cache for performance)
        print("\nLoading channel data for validation...")
        current_channels = await get_all_channels(use_cache=True, dry_run=dry_run)
        
        # Process channels in batches if batch_size > 0
        batch_channels = []
        batch_count = 0
        
        for i, channel in enumerate(channels):
            # Skip invalid channels
            if not channel.get("channel_id") or not channel.get("name"):
                print(f"⚠️  Skipping invalid channel: {channel}")
                skipped += 1
                continue
                
            action = channel.get("action", "").lower()
            
            # Skip if action is "keep" or invalid
            if not action or action == ChannelAction.KEEP.value:
                continue
                
            # Validate action is supported
            if action not in ChannelAction.values():
                print(f"⚠️  Skipping unsupported action '{action}' for channel {channel['name']}")
                skipped += 1
                continue
            
            # For batch processing
            if batch_size > 0:
                batch_channels.append(channel)
                batch_count += 1
                
                # Process batch when we reach batch_size or at the end
                if batch_count >= batch_size or i == len(channels) - 1:
                    if batch_channels:
                        # Display batch summary
                        print("\n" + "=" * 80)
                        print(f"Batch of {len(batch_channels)} channels:")
                        for idx, ch in enumerate(batch_channels, 1):
                            ch_action = ch.get("action", "").lower()
                            ch_name = f"#{ch['name']}"
                            if ch.get("is_private"):
                                ch_name = f"🔒 {ch_name}"
                            
                            action_message = action_desc.get(ch_action, ch_action)
                            if ch_action in [ChannelAction.ARCHIVE.value, ChannelAction.RENAME.value]:
                                action_message = f"{action_message} {ch.get('target_value', '')}"
                                
                            print(f"{idx}. {action_message}: {ch_name}")
                        
                        # Get batch approval
                        while True:
                            response = input("\nPress 'y' to approve all, 'n' to skip all, 'i' for individual review, or 'q' to quit: ").lower()
                            if response == 'q':
                                raise KeyboardInterrupt("User requested to quit")
                            if response in ['y', 'n', 'i']:
                                break
                        
                        if response == 'y':
                            # Process all channels in batch
                            for ch in batch_channels:
                                result = await process_single_channel(ch, handler, client, current_channels, dry_run)
                                if result == "success":
                                    successful += 1
                                    successful_channel_ids.append(ch["channel_id"])
                                    last_action = (ch, ch.get("action"), ch.get("target_value"))
                                elif result == "failed":
                                    failed += 1
                                elif result == "skipped":
                                    skipped += 1
                        elif response == 'n':
                            # Skip all channels in batch
                            skipped += len(batch_channels)
                            print(f"⏭️  Skipped {len(batch_channels)} actions")
                        elif response == 'i':
                            # Process channels individually
                            for ch in batch_channels:
                                try:
                                    approved = await get_user_approval(client, ch, ch.get("action"), ch.get("target_value"), current_channels)
                                    if not approved:
                                        print("⏭️  Action skipped")
                                        skipped += 1
                                        continue
                                except KeyboardInterrupt:
                                    print("\n⛔ Process interrupted by user")
                                    raise
                                except Exception as e:
                                    print(f"❌ Error getting approval for {ch['name']}: {str(e)}")
                                    failed += 1
                                    continue
                                
                                result = await process_single_channel(ch, handler, client, current_channels, dry_run)
                                if result == "success":
                                    successful += 1
                                    successful_channel_ids.append(ch["channel_id"])
                                    last_action = (ch, ch.get("action"), ch.get("target_value"))
                                elif result == "failed":
                                    failed += 1
                                elif result == "skipped":
                                    skipped += 1
                        
                        # Reset batch
                        batch_channels = []
                        batch_count = 0
                        
                        # Small delay between batches
                        await asyncio.sleep(0.5)
            else:
                # Individual processing (original behavior)
                try:
                    approved = await get_user_approval(client, channel, action, channel.get("target_value"), current_channels)
                    if not approved:
                        print("⏭️  Action skipped")
                        skipped += 1
                        continue
                except KeyboardInterrupt:
                    print("\n⛔ Process interrupted by user")
                    break
                except Exception as e:
                    print(f"❌ Error getting approval for {channel['name']}: {str(e)}")
                    failed += 1
                    continue
                
                result = await process_single_channel(channel, handler, client, current_channels, dry_run)
                if result == "success":
                    successful += 1
                    successful_channel_ids.append(channel["channel_id"])
                    last_action = (channel, action, channel.get("target_value"))
                elif result == "failed":
                    failed += 1
                elif result == "skipped":
                    skipped += 1
    
    except KeyboardInterrupt:
        print("\n⛔ Process interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
    
    finally:
        print("\nExecution Summary:")
        print(f"Successful actions: {successful}")
        print(f"Failed actions: {failed}")
        print(f"Skipped actions: {skipped}")
        print(f"Total channels processed: {successful + failed + skipped}")
        
        # Add summary of what was done
        if successful > 0:
            action_counts = {}
            for channel in channels:
                if channel.get("channel_id") in successful_channel_ids:
                    action = channel.get("action", "").lower()
                    action_counts[action] = action_counts.get(action, 0) + 1
            
            summary_parts = []
            for action, count in action_counts.items():
                if action == ChannelAction.ARCHIVE.value:
                    summary_parts.append(f"{count} archived")
                elif action == ChannelAction.RENAME.value:
                    summary_parts.append(f"{count} renamed")
            
            if summary_parts:
                print(f"\nCompleted: {', '.join(summary_parts)}")
        
        if last_action and last_action[1] == ChannelAction.ARCHIVE.value:
            print("\nNote: To undo the last archive action, use the Slack UI:")
            print("1. Go to channel #" + last_action[0]['name'])
            print("2. Click the gear icon ⚙️")
            print("3. Select 'Additional options'")
            print("4. Choose 'Unarchive channel'")
        
        return successful_channel_ids  # Return the list of successful channel IDs

# Helper function to process a single channel
async def process_single_channel(channel, handler, client, current_channels, dry_run):
    """Process a single channel and return the result status."""
    channel_name = f"#{channel['name']}"
    if channel.get("is_private"):
        channel_name = f"🔒 {channel_name}"
    
    action = channel.get("action", "").lower()
    action_message = {
        ChannelAction.KEEP.value: "keep as is",
        ChannelAction.ARCHIVE.value: "archive",
        ChannelAction.RENAME.value: "rename to"
    }.get(action, action)
    
    if action in [ChannelAction.ARCHIVE.value, ChannelAction.RENAME.value]:
        action_message = f"{action_message} {channel.get('target_value', '')}"
    
    if dry_run:
        print(f"✅ Would {action_message}: {channel_name}")
        return "success"
    
    # Verify channel still exists and is in expected state before executing
    try:
        channel_info = await get_channel_info(client, channel["channel_id"])
        if not channel_info:
            print(f"❌ Channel {channel['name']} no longer exists!")
            return "skipped"
        if channel_info.get("is_archived"):
            print(f"❌ Channel {channel['name']} is already archived!")
            return "skipped"
        if channel_info.get("name") != channel["name"]:
            print(f"❌ Channel has been renamed from {channel['name']} to {channel_info['name']}!")
            return "skipped"
            
        # Now execute the action
        result = await handler.execute_action(
            channel_id=channel["channel_id"],
            channel_name=channel["name"],
            action=action,
            target_value=channel.get("target_value", "")
        )
        
        if result.success:
            print(f"✅ {result.message}")
            
            # Update channel name in our data after successful rename
            if action == ChannelAction.RENAME.value:
                channel["name"] = channel.get("target_value")
            
            return "success"
        else:
            print(f"❌ {result.message}")
            return "failed"
    except Exception as e:
        print(f"❌ Error processing {channel['name']}: {str(e)}")
        return "skipped" 